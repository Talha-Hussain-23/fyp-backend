"""
Enhanced Rate Limiter with Per-User Limiting
Implements both IP-based and user-based rate limiting
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def get_real_ip(request: Request) -> str:
    """
    Get the real IP address of the client, handling proxies (X-Forwarded-For).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For can contain multiple IPs, get the first one
        return forwarded.split(",")[0].strip()
    
    # Fallback to direct connection
    if request.client:
        return request.client.host
    
    return "unknown"


def get_user_identifier(request: Request) -> str:
    """
    Get user identifier for rate limiting.
    Uses user ID if authenticated, otherwise falls back to IP address.
    """
    try:
        # Try to get user from request state (set by auth middleware)
        if hasattr(request.state, 'user') and request.state.user:
            user_id = getattr(request.state.user, 'id', None)
            if user_id:
                return f"user:{user_id}"
        
        # Try to get from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # Extract user from JWT (simplified - actual implementation would decode JWT)
            token = auth_header.replace("Bearer ", "")
            # For now, use token hash as identifier
            import hashlib
            token_hash = hashlib.md5(token.encode()).hexdigest()[:16]
            return f"token:{token_hash}"
        
    except Exception as e:
        logger.debug(f"Could not extract user identifier: {e}")
    
    # Fallback to IP-based limiting
    return f"ip:{get_real_ip(request)}"


# Initialize Limiters
# IP-based limiter (for public endpoints)
ip_limiter = Limiter(key_func=get_real_ip)

# User-based limiter (for authenticated endpoints)
user_limiter = Limiter(key_func=get_user_identifier)

# Default limiter (uses user if available, IP otherwise)
# explicitly locked to memory storage for legendary standalone performance
limiter = Limiter(key_func=get_user_identifier, storage_uri="memory://")


__all__ = ['limiter', 'ip_limiter', 'user_limiter', 'get_real_ip', 'get_user_identifier']
