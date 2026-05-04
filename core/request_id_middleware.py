"""
Request ID Tracking Middleware
Adds unique request ID to every request for tracing and debugging
"""
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from core.logging_service import logger


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add unique request ID to every request
    Useful for distributed tracing and debugging
    """
    
    async def dispatch(self, request: Request, call_next):
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Add request ID to request state
        request.state.request_id = request_id
        
        # Log request
        logger.info(
            f"Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "url": str(request.url),
                "client": request.client.host if request.client else "unknown"
            }
        )
        
        # Process request
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        # Log response
        logger.info(
            f"Request completed",
            extra={
                "request_id": request_id,
                "status_code": response.status_code
            }
        )
        
        return response
