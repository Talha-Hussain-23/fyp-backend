"""
Centralized Error Handler Middleware
Logs all errors to database and provides graceful error responses
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import traceback
import structlog
from typing import Optional
from utils import get_db

logger = structlog.get_logger(__name__)

class ErrorTracker:
    """Centralized error logging and tracking"""
    
    @staticmethod
    async def log_error(
        error: Exception,
        context: dict,
        user_id: Optional[str] = None,
        severity: str = "ERROR"
    ) -> str:
        """
        Log error to database for tracking and debugging
        
        Args:
            error: The exception that occurred
            context: Additional context (request path, params, etc.)
            user_id: User who encountered the error (if available)
            severity: ERROR, WARNING, CRITICAL
            
        Returns:
            error_id: ID of the logged error
        """
        try:
            db = await get_db()
            
            error_doc = {
                "error_type": type(error).__name__,
                "message": str(error),
                "severity": severity,
                "context": context,
                "user_id": user_id,
                "stack_trace": traceback.format_exc(),
                "timestamp": datetime.now(timezone.utc),
                "resolved": False
            }
            
            result = await db.error_logs.insert_one(error_doc)
            error_id = str(result.inserted_id)
            
            # Log to application logger as well
            # Log to application logger as well
            log_method = getattr(logger, severity.lower(), logger.error)
            log_method(
                "error_tracked",
                error_id=error_id,
                error=str(error),
                context_keys=list(context.keys())
            )
            
            return error_id
            
        except Exception as e:
            # Fallback: If error logging fails
            logger.critical("error_logging_failed", error=str(e), original_error=str(error))
            return None
    
    @staticmethod
    def get_user_friendly_message(error: Exception) -> str:
        """Convert technical errors to user-friendly messages"""
        
        error_messages = {
            "ValidationError": "Invalid input. Please check your data and try again.",
            "AuthenticationError": "Session expired. Please log in again.",
            "PermissionError": "You don't have permission to perform this action.",
            "NotFoundError": "The requested resource was not found.",
            "TimeoutError": "Request timed out. Please try again.",
            "ConnectionError": "Connection lost. Please check your internet.",
            "DatabaseError": "Database temporarily unavailable. Please try again.",
            "AIProviderError": "AI service temporarily unavailable. Using fallback.",
        }
        
        error_type = type(error).__name__
        return error_messages.get(error_type, "An unexpected error occurred. Please try again or contact support.")


async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for FastAPI
    Catches all unhandled exceptions and returns user-friendly responses
    """
    
    # Extract user info if available
    user_id = None
    try:
        # Try to get user from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
    except:
        pass
    
    # Build context
    context = {
        "path": str(request.url.path),
        "method": request.method,
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
    
    # Determine severity
    severity = "CRITICAL" if isinstance(exc, (DatabaseError, SystemError)) else "ERROR"
    
    # Log error
    error_id = await ErrorTracker.log_error(exc, context, user_id, severity)
    
    # Get user-friendly message
    user_message = ErrorTracker.get_user_friendly_message(exc)
    
    # Map exceptions to status codes
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    if isinstance(exc, AuthenticationError):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, PermissionError):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, (ValueError, TypeError)):
        status_code = status.HTTP_400_BAD_REQUEST
    
    # Return appropriate response
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": user_message,
            "error_id": error_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


# Custom exception classes
class DatabaseError(Exception):
    """Raised when database operations fail"""
    pass

class AIProviderError(Exception):
    """Raised when AI provider is unavailable"""
    pass

class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass
