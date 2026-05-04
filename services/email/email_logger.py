"""
Professional Email Logger Service (Async)
Provides comprehensive logging for all email operations with structured data
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from bson import ObjectId

logger = logging.getLogger("email_service")

class EmailLogger:
    """Centralized email logging with database and file logging (Async)"""
    
    def __init__(self, db=None):
        self.db = db
    
    async def log_attempt(
        self,
        interview_id: str,
        candidate_email: str,
        email_type: str,
        status: str,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        attempt_number: int = 1
    ) -> Optional[str]:
        """Log email attempt with full context (Async)"""
        log_entry = {
            "interview_id": interview_id,
            "candidate_email": candidate_email,
            "email_type": email_type,
            "status": status,
            "error": error,
            "metadata": metadata or {},
            "attempt_number": attempt_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc)
        }
        
        # Log to file
        log_message = f"Email {status} | Interview: {interview_id} | To: {candidate_email} | Type: {email_type} | Attempt: {attempt_number}"
        if error: logger.error(f"{log_message} | Error: {error}")
        elif status == "success": logger.info(log_message)
        else: logger.warning(log_message)
        
        if self.db is not None:
            try:
                result = await self.db.email_audit_log.insert_one(log_entry)
                return str(result.inserted_id)
            except Exception as e:
                logger.error(f"Failed to log to database: {e}")
        return None
    
    async def log_success(self, interview_id: str, candidate_email: str, email_type: str, message_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        meta = metadata or {}
        if message_id: meta["message_id"] = message_id
        return await self.log_attempt(interview_id=interview_id, candidate_email=candidate_email, email_type=email_type, status="success", metadata=meta)
    
    async def log_failure(self, interview_id: str, candidate_email: str, email_type: str, error: str, attempt_number: int = 1, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        log_id = await self.log_attempt(interview_id=interview_id, candidate_email=candidate_email, email_type=email_type, status="failed", error=error, attempt_number=attempt_number, metadata=metadata)
        if self.db is not None:
            try:
                await self.db.email_failures.insert_one({
                    "interview_id": interview_id, "candidate_email": candidate_email, "email_type": email_type,
                    "error": error, "attempt_number": attempt_number, "timestamp": datetime.now(timezone.utc).isoformat(),
                    "created_at": datetime.now(timezone.utc)
                })
            except Exception as e:
                logger.error(f"Failed to log failure: {e}")
        return log_id
    
    async def log_retry(self, interview_id: str, candidate_email: str, email_type: str, attempt_number: int, error: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        return await self.log_attempt(interview_id=interview_id, candidate_email=candidate_email, email_type=email_type, status="retrying", error=error, attempt_number=attempt_number, metadata=metadata)
    
    async def get_email_history(self, interview_id: Optional[str] = None, candidate_email: Optional[str] = None, limit: int = 100) -> List[Dict]:
        if self.db is None: return []
        query = {}
        if interview_id: query["interview_id"] = interview_id
        if candidate_email: query["candidate_email"] = candidate_email
        try:
            logs = await self.db.email_audit_log.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
            for log in logs: log["_id"] = str(log["_id"])
            return logs
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []

    async def get_failed_emails(self, limit: int = 100) -> List[Dict]:
        if self.db is None: return []
        try:
            failures = await self.db.email_failures.find().sort("created_at", -1).limit(limit).to_list(length=limit)
            for f in failures: f["_id"] = str(f["_id"])
            return failures
        except Exception as e:
            logger.error(f"Failed to get failures: {e}")
            return []

_email_logger = None

def get_email_logger(db=None):
    global _email_logger
    if _email_logger is None or (_email_logger.db is None and db is not None):
        _email_logger = EmailLogger(db)
    return _email_logger
