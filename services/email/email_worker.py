import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pymongo import ReturnDocument, ASCENDING
from bson import ObjectId

from utils import get_db

logger = logging.getLogger(__name__)

# Constants
COLLECTION_NAME = "email_queue"
POLL_INTERVAL_SECONDS = 10

class EmailWorker:
    """
    Background worker that polls MongoDB for pending emails.
    Ensures At-Least-Once delivery with Dead Letter Queue support.
    (Async Optimized)
    """
    
    def __init__(self):
        self.running = False

    async def _get_db(self):
        """Helper to get async database instance"""
        from utils.db import get_db
        return await get_db()

    async def start(self):
        """Start the worker loop"""
        self.running = True
        logger.info("📧 Email Worker Started. Polling queue...")
        while self.running:
            try:
                await self.process_queue()
            except Exception as e:
                logger.error(f"Error in EmailWorker loop: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def stop(self):
        """Stop the worker"""
        self.running = False
        logger.info("📧 Email Worker Stopped.")

    async def process_queue(self):
        """
        Find and process one pending task.
        Uses find_one_and_update for atomic locking.
        """
        db = await self._get_db()
        now = datetime.now(timezone.utc)
        
        # 1. Find a task that is PENDING, queued or FAILED (retryable) and ready
        query = {
            "$or": [
                {"status": {"$in": ["PENDING", "queued"]}},
                {"status": "FAILED", "next_retry": {"$lte": now.isoformat()}}
            ]
        }
        
        # Atomically lock the task by setting status to PROCESSING
        task = await db[COLLECTION_NAME].find_one_and_update(
            query,
            {"$set": {"status": "PROCESSING", "last_attempt": now.isoformat()}},
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER
        )
        
        if not task:
            return  # Queue is empty
        
        # Record total attempts
        attempts = task.get("attempts", 0) + 1
        await db[COLLECTION_NAME].update_one(
            {"_id": task["_id"]},
            {"$set": {"attempts": attempts}}
        )

        logger.info(f"📨 Processing Email Task {task.get('task_id')} to {task['to_email']} (Attempt {attempts})")
        
        await self.execute_task(db, task)

    async def execute_task(self, db, task: dict):
        """Execute the email sending logic using immediate delivery function"""
        try:
            to_email = task["to_email"]
            subject = task.get("subject")
            template_name = task["template_name"]
            variables = task.get("template_data", {})
            
            from services.email.email_service import send_templated_email
            
            # Execute async send function directly
            await send_templated_email(
                to_email=to_email,
                template_name=template_name,
                variables=variables,
                subject=subject,
                db=db
            )
            
            # Mark as COMPLETED
            await db[COLLECTION_NAME].update_one(
                {"_id": task["_id"]},
                {"$set": {"status": "COMPLETED", "completed_at": datetime.now(timezone.utc).isoformat()}}
            )
            logger.info(f"✅ Email Task {task.get('task_id')} COMPLETED")

        except Exception as e:
            logger.error(f"❌ Email Task {task.get('task_id')} FAILED: {e}")
            await self.handle_failure(db, task, str(e))

    async def handle_failure(self, db, task: dict, error_msg: str):
        """Handle retry logic or move to Dead Letter Queue"""
        max_attempts = task.get("max_attempts", 5)
        current_attempts = task.get("attempts", 1)
        
        if current_attempts >= max_attempts:
            # Move to DEAD LETTER QUEUE
            await db[COLLECTION_NAME].update_one(
                {"_id": task["_id"]},
                {"$set": {
                    "status": "DEAD_LETTER",
                    "error_log": task.get("error_log", []) + [f"{datetime.now(timezone.utc).isoformat()}: {error_msg}"]
                }}
            )
            logger.critical(f"💀 Email Task {task.get('task_id')} moved to DEAD LETTER QUEUE. Error: {error_msg}")
        else:
            # Schedule Retry (Exponential Backoff)
            backoff_minutes = 2 ** (current_attempts - 1)
            next_retry = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
            
            await db[COLLECTION_NAME].update_one(
                {"_id": task["_id"]},
                {"$set": {
                    "status": "FAILED",
                    "next_retry": next_retry.isoformat(),
                    "error_log": task.get("error_log", []) + [f"{datetime.now(timezone.utc).isoformat()}: {error_msg}"]
                }}
            )
            logger.warning(f"⚠️ Email Task {task.get('task_id')} scheduled for retry in {backoff_minutes}m")

# Global Worker Instance
email_worker = EmailWorker()
