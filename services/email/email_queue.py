"""
Professional Email Queue Service
Handles background email processing with rate limiting and retry logic
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Any
from pymongo.database import Database
from bson import ObjectId
import logging

logger = logging.getLogger("email_queue")


class EmailQueue:
    """
    Background email queue with rate limiting and concurrent processing
    """
    
    def __init__(
        self,
        db: Database,
        max_concurrent: int = 5,
        rate_limit_per_minute: int = 60,
        max_retries: int = 3
    ):
        """
        Initialize email queue
        
        Args:
            db: MongoDB database instance
            max_concurrent: Maximum concurrent email sends
            rate_limit_per_minute: Maximum emails per minute
            max_retries: Maximum retry attempts for failed emails
        """
        self.db = db
        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit_per_minute
        self.max_retries = max_retries
        self.queue = asyncio.Queue()
        self.processing = False
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.rate_limiter = RateLimiter(rate_limit_per_minute)
    
    async def enqueue_email(
        self,
        interview_id: str,
        email_type: str,
        email_data: Dict[str, Any],
        priority: int = 5
    ) -> str:
        """
        Add email to queue
        
        Args:
            interview_id: Interview ID
            email_type: Type of email
            email_data: Email data (to, subject, body, etc.)
            priority: Priority (1-10, lower is higher priority)
            
        Returns:
            Queue entry ID
        """
        queue_entry = {
            "interview_id": interview_id,
            "email_type": email_type,
            "email_data": email_data,
            "status": "PENDING",
            "priority": priority,
            "attempts": 0,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc)
        }
        
        # Persist to database
        result = self.db.email_queue.insert_one(queue_entry)
        queue_id = str(result.inserted_id)
        
        # Add to in-memory queue
        await self.queue.put({
            "queue_id": queue_id,
            **queue_entry
        })
        
        logger.info(f"Email queued: {queue_id} for interview {interview_id}")
        
        return queue_id
    
    async def process_queue(self):
        """Process emails from queue with rate limiting"""
        self.processing = True
        logger.info("Email queue processor started")
        
        while self.processing:
            try:
                # Get email from queue (with timeout to allow checking processing flag)
                try:
                    email_item = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process email with concurrency control
                asyncio.create_task(self._process_email(email_item))
                
            except Exception as e:
                logger.error(f"Error in queue processor: {e}")
                await asyncio.sleep(1)
    
    async def _process_email(self, email_item: Dict[str, Any]):
        """Process single email with rate limiting and retry"""
        queue_id = email_item["queue_id"]
        
        async with self.semaphore:  # Limit concurrent sends
            await self.rate_limiter.acquire()  # Rate limiting
            
            try:
                # Update status to processing
                self.db.email_queue.update_one(
                    {"_id": ObjectId(queue_id)},
                    {
                        "$set": {
                            "status": "processing",
                            "processing_at": datetime.now(timezone.utc).isoformat()
                        },
                        "$inc": {"attempts": 1}
                    }
                )
                
                # Send email (import here to avoid circular dependency)
                from services.email.email_service import send_interview_invitation_email
                
                email_data = email_item["email_data"]
                result = send_interview_invitation_email(**email_data)
                
                # Mark as sent
                self.db.email_queue.update_one(
                    {"_id": ObjectId(queue_id)},
                    {
                        "$set": {
                            "status": "sent",
                            "sent_at": datetime.now(timezone.utc).isoformat(),
                            "result": result
                        }
                    }
                )
                
                logger.info(f"Email sent successfully: {queue_id}")
                
            except Exception as e:
                logger.error(f"Failed to send email {queue_id}: {e}")
                
                # Get current attempts
                queue_doc = self.db.email_queue.find_one({"_id": ObjectId(queue_id)})
                attempts = queue_doc.get("attempts", 0) if queue_doc else 0
                
                if attempts < self.max_retries:
                    # Retry with exponential backoff
                    retry_delay = 2 ** attempts  # 2, 4, 8 seconds
                    
                    self.db.email_queue.update_one(
                        {"_id": ObjectId(queue_id)},
                        {
                            "$set": {
                                "status": "retry_scheduled",
                                "last_error": str(e),
                                "retry_at": (
                                    datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
                                ).isoformat()
                            }
                        }
                    )
                    
                    # Re-queue after delay
                    await asyncio.sleep(retry_delay)
                    await self.queue.put(email_item)
                    
                    logger.info(f"Email {queue_id} scheduled for retry in {retry_delay}s")
                else:
                    # Max retries exceeded
                    self.db.email_queue.update_one(
                        {"_id": ObjectId(queue_id)},
                        {
                            "$set": {
                                "status": "failed",
                                "failed_at": datetime.now(timezone.utc).isoformat(),
                                "last_error": str(e)
                            }
                        }
                    )
                    
                    logger.error(f"Email {queue_id} failed after {attempts} attempts")
    
    async def load_pending_emails(self):
        """Load pending emails from database on startup"""
        try:
            pending = self.db.email_queue.find({
                "status": {"$in": ["PENDING", "queued", "retry_scheduled"]}
            }).sort("priority", 1).sort("created_at", 1)
            
            count = 0
            for email_doc in pending:
                # Check if retry time has passed
                retry_at = email_doc.get("retry_at")
                if retry_at:
                    retry_time = datetime.fromisoformat(retry_at)
                    if datetime.now(timezone.utc) < retry_time:
                        continue  # Skip, not ready for retry yet
                
                await self.queue.put({
                    "queue_id": str(email_doc["_id"]),
                    **email_doc
                })
                count += 1
            
            logger.info(f"Loaded {count} pending emails from database")
            
        except Exception as e:
            logger.error(f"Failed to load pending emails: {e}")
    
    def stop(self):
        """Stop queue processor"""
        self.processing = False
        logger.info("Email queue processor stopped")
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        try:
            stats = {
                "queued": self.db.email_queue.count_documents({"status": "queued"}),
                "processing": self.db.email_queue.count_documents({"status": "processing"}),
                "sent": self.db.email_queue.count_documents({"status": "sent"}),
                "failed": self.db.email_queue.count_documents({"status": "failed"}),
                "retry_scheduled": self.db.email_queue.count_documents({"status": "retry_scheduled"}),
                "in_memory_queue_size": self.queue.qsize()
            }
            return stats
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {}


class RateLimiter:
    """Simple rate limiter for email sending"""
    
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.tokens = max_per_minute
        self.last_refill = datetime.now(timezone.utc)
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire token for sending email"""
        async with self.lock:
            # Refill tokens based on time elapsed
            now = datetime.now(timezone.utc)
            elapsed = (now - self.last_refill).total_seconds()
            
            if elapsed >= 60:  # Refill every minute
                self.tokens = self.max_per_minute
                self.last_refill = now
            
            # Wait if no tokens available
            while self.tokens <= 0:
                await asyncio.sleep(1)
                now = datetime.now(timezone.utc)
                elapsed = (now - self.last_refill).total_seconds()
                if elapsed >= 60:
                    self.tokens = self.max_per_minute
                    self.last_refill = now
            
            self.tokens -= 1


# Global email queue instance
_email_queue: Optional[EmailQueue] = None


def get_email_queue(db: Database) -> EmailQueue:
    """Get or create global email queue instance"""
    global _email_queue
    
    if _email_queue is None:
        _email_queue = EmailQueue(db)
    
    return _email_queue


async def start_email_queue_processor(db: Database):
    """Start email queue processor in background"""
    queue = get_email_queue(db)
    await queue.load_pending_emails()
    await queue.process_queue()
