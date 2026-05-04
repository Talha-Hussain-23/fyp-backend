"""
CSRF Protection Middleware
Protects against Cross-Site Request Forgery attacks
"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import secrets
from typing import Callable


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF Protection Middleware for FastAPI
    
    Validates CSRF tokens on state-changing requests (POST, PUT, DELETE, PATCH)
    """
    
    def __init__(self, app, secret_key: str = None):
        super().__init__(app)
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        
        # Exempt paths (public endpoints that don't need CSRF)
        self.exempt_paths = [
            "/api/auth/login",
            "/api/auth/signup",
            "/api/auth/verify-email",
            "/api/auth/request-password-reset",
            "/api/auth/reset-password",
            "/api/public/",
            "/docs",
            "/openapi.json",
            "/health"
        ]
        
        # Methods that require CSRF protection
        self.protected_methods = ["POST", "PUT", "DELETE", "PATCH"]
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Process request and validate CSRF token"""
        
        # Skip CSRF check for exempt paths
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)
        
        # Skip CSRF check for safe methods
        if request.method not in self.protected_methods:
            return await call_next(request)
        
        # Get CSRF token from header
        csrf_token = request.headers.get("X-CSRF-Token")
        
        # Get CSRF token from cookie
        csrf_cookie = request.cookies.get("csrf_token")
        
        # Validate token
        if not csrf_token or not csrf_cookie or csrf_token != csrf_cookie:
            raise HTTPException(
                status_code=403,
                detail="CSRF token validation failed"
            )
        
        # Process request
        response = await call_next(request)
        
        return response


def generate_csrf_token() -> str:
    """Generate a new CSRF token"""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response, token: str):
    """Set CSRF token in cookie"""
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=True,
        secure=True,  # Only send over HTTPS
        samesite="strict",
        max_age=3600  # 1 hour
    )
    return response
