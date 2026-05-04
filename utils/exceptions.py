"""
Custom Exception Classes
Centralized error handling for the application
"""
from typing import Optional, Any


class AppException(Exception):
    """Base exception for application errors."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: Optional[str] = None,
        details: Optional[dict] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or f"ERR_{status_code}"
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> dict:
        """Convert exception to response dict."""
        return {
            "success": False,
            "error": {
                "code": self.error_code,
                "message": self.message,
                "details": self.details
            }
        }


class NotFoundError(AppException):
    """Resource not found (404)."""
    
    def __init__(self, resource: str, resource_id: Optional[str] = None):
        message = f"{resource} not found"
        if resource_id:
            message = f"{resource} with ID '{resource_id}' not found"
        super().__init__(
            message=message,
            status_code=404,
            error_code="NOT_FOUND"
        )


class ForbiddenError(AppException):
    """Access denied (403)."""
    
    def __init__(self, message: str = "Access denied", required_role: Optional[str] = None):
        details = {}
        if required_role:
            details["required_role"] = required_role
        super().__init__(
            message=message,
            status_code=403,
            error_code="FORBIDDEN",
            details=details
        )


class UnauthorizedError(AppException):
    """Authentication required (401)."""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            status_code=401,
            error_code="UNAUTHORIZED"
        )


class ValidationError(AppException):
    """Validation failed (422)."""
    
    def __init__(self, message: str, field: Optional[str] = None, errors: Optional[list] = None):
        details = {}
        if field:
            details["field"] = field
        if errors:
            details["errors"] = errors
        super().__init__(
            message=message,
            status_code=422,
            error_code="VALIDATION_ERROR",
            details=details
        )


class ConflictError(AppException):
    """Resource conflict (409)."""
    
    def __init__(self, message: str, resource: Optional[str] = None):
        details = {}
        if resource:
            details["resource"] = resource
        super().__init__(
            message=message,
            status_code=409,
            error_code="CONFLICT",
            details=details
        )


class RateLimitError(AppException):
    """Rate limit exceeded (429)."""
    
    def __init__(self, retry_after: Optional[int] = None):
        details = {}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(
            message="Rate limit exceeded. Please try again later.",
            status_code=429,
            error_code="RATE_LIMIT_EXCEEDED",
            details=details
        )


class ExternalServiceError(AppException):
    """External service failed (502)."""
    
    def __init__(self, service: str, message: Optional[str] = None):
        super().__init__(
            message=message or f"External service '{service}' is unavailable",
            status_code=502,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service}
        )
