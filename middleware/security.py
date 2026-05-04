"""
Enhanced Security Headers Middleware
Implements comprehensive security headers for production
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import os


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add comprehensive security headers to all responses
    Implements OWASP security best practices
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Get environment
        from core.config import settings
        is_production = settings.ENVIRONMENT == 'production'
        base_url = settings.active_frontend_url
        
        # Strict-Transport-Security (HSTS) - Force HTTPS
        if is_production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        # X-Content-Type-Options - Prevent MIME sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # X-Frame-Options - Prevent clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        
        # X-XSS-Protection - Enable browser XSS protection
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer-Policy - Control referrer information
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions-Policy - Control browser features
        response.headers['Permissions-Policy'] = (
            'geolocation=(), '
            'microphone=(), '
            'camera=(self), '
            'payment=(), '
            'usb=(), '
            'magnetometer=(), '
            'gyroscope=(), '
            'accelerometer=()'
        )
        
        # Content-Security-Policy - Prevent XSS and injection attacks
        csp_directives = [
            "default-src 'self'",
            f"connect-src 'self' {base_url} https://*.mongodb.net wss://*",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: https: blob:",
            "media-src 'self' blob:",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'"
        ]
        
        # Relaxed CSP for development
        if not is_production:
            csp_directives = [
                "default-src 'self' 'unsafe-inline' 'unsafe-eval'",
                "connect-src 'self' http://localhost:* ws://localhost:* wss://*",
                "img-src 'self' data: https: blob:",
                "media-src 'self' blob:"
            ]
        
        response.headers['Content-Security-Policy'] = '; '.join(csp_directives)
        
        # X-Permitted-Cross-Domain-Policies - Restrict cross-domain policies
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
        
        # Cache-Control for sensitive endpoints
        if '/api/auth/' in request.url.path or '/api/user/' in request.url.path:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response.headers['Pragma'] = 'no-cache'
        
        # Server header - Hide server information
        response.headers['Server'] = 'SmartHiring'
        
        return response
