"""
Logging & Monitoring Service (Refactored for Production)
Uses structlog for structured JSON logging to stdout.
Retains audit logging to MongoDB for compliance.
"""

import logging
import sys
import structlog
from datetime import datetime, timezone
from typing import Dict, Optional, Any, TYPE_CHECKING
import traceback
import time

# Use TYPE_CHECKING to avoid importing pymongo runtime issues
if TYPE_CHECKING:
    from pymongo.database import Database
else:
    Database = Any

# --- Configure Structlog ---
def configure_logging():
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(), 
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=shared_processors + [
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )

# Initialize on module load
configure_logging()
logger = structlog.get_logger()

class LoggingService:
    """
    Centralized logging service using Structlog.
    Writes logs to stdout (JSON) for external aggregators (Datadog/CloudWatch).
    """
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db
        # We no longer strictly need DB for general logging, only for Audit
    
    def log_request(self, method: str, path: str, user_id: Optional[str] = None,
                   status_code: int = 200, response_time_ms: float = 0,
                   ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """Log API request using structlog"""
        
        # Log to stdout (JSON)
        logger.info(
            "api_request",
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=round(response_time_ms, 2),
            user_id=user_id,
            ip=ip_address,
            user_agent=user_agent
        )
        
        # Store in database (Legacy support / Analysis)
        # In robust systems, we might skip this and rely on ELK, but keeping for now
        if self.db is not None:
            try:
                self.db.api_logs.insert_one({
                    "type": "request",
                    "method": method,
                    "path": path,
                    "user_id": user_id,
                    "status_code": status_code,
                    "response_time_ms": response_time_ms,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                pass # Fail silently, don't crash app for logs

    def log_error(self, error: Exception, context: Dict = None, user_id: Optional[str] = None,
                 path: Optional[str] = None, request_data: Dict = None):
        """Log error with stack trace"""
        
        logger.error(
            "exception",
            error=str(error),
            error_type=type(error).__name__,
            path=path,
            user_id=user_id,
            request_data=request_data,
            context=context,
            exc_info=True # Structlog handles stack trace
        )
        
        # Store in database
        if self.db is not None:
            try:
                self.db.api_logs.insert_one({
                    "type": "error",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "stack_trace": traceback.format_exc(),
                    "context": context or {},
                    "user_id": user_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                pass

    def log_performance(self, operation: str, duration_ms: float, details: Dict = None):
        """Log performance metrics"""
        logger.info(
            "performance",
            operation=operation,
            duration_ms=round(duration_ms, 2),
            details=details
        )
        
        if duration_ms > 500:
            logger.warning("slow_operation", operation=operation, duration_ms=duration_ms)

    def log_security_event(self, event_type: str, user_id: Optional[str] = None,
                          details: Dict = None, ip_address: Optional[str] = None):
        """Log security-related events"""
        logger.warning(
            "security_event",
            event_type=event_type,
            user_id=user_id,
            ip=ip_address,
            details=details
        )
        
        if self.db is not None:
            try:
                self.db.api_logs.insert_one({
                    "type": "security",
                    "event_type": event_type,
                    "user_id": user_id,
                    "details": details or {},
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                pass

# Global logging service instance
_logging_service: Optional[LoggingService] = None

def init_logging_service(db):
    """Initialize global logging service"""
    global _logging_service
    _logging_service = LoggingService(db)

def get_logging_service() -> LoggingService:
    """Get global logging service instance"""
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService()
    return _logging_service

async def log_audit_event(db, user_id: str, action: str, entity_type: str,
                           entity_id: Optional[str] = None, details: Dict = None,
                           ip_address: Optional[str] = None):
    """Log audit event (Async)"""
    from core.models import create_audit_log_document
    try:
        audit_log = create_audit_log_document(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip_address=ip_address
        )
        await db.audit_logs.insert_one(audit_log)
        logger.info("audit_event", user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id)
    except Exception as e:
        logger.error("audit_log_failed", error=str(e))

def performance_monitor(operation_name: str):
    """Decorator for monitoring function performance"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                get_logging_service().log_performance(operation_name, duration_ms)
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                get_logging_service().log_error(e, {"operation": operation_name})
                raise
        return wrapper
    return decorator

__all__ = [
    'LoggingService',
    'get_logging_service',
    'init_logging_service',
    'log_audit_event',
    'performance_monitor',
    'logger'
]
