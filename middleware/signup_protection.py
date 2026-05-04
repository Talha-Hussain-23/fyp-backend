"""
Signup Protection Middleware
Implements IP-based brute force protection for recruiter signup endpoint

This middleware tracks failed signup attempts by IP address and blocks IPs
that exceed the maximum allowed attempts within a time window.

Security Features:
- Tracks failed attempts per IP
- Blocks IPs after MAX_SIGNUP_ATTEMPTS (default: 5)
- Auto-expires blocks after SIGNUP_BLOCK_TIME (default: 60 minutes)
- Clears attempts on successful signup
- Returns 429 with Retry-After header when blocked

Professional In-Memory IP Tracking (Platinum Standalone Mode)
"""
import os
import time
from typing import Dict, List
from fastapi import Request, HTTPException
from core.rate_limiter import get_real_ip
from utils import logger


_signup_attempts: Dict[str, List[float]] = {}
_blocked_ips: Dict[str, float] = {}

# Configuration from environment
MAX_ATTEMPTS = int(os.getenv("MAX_SIGNUP_ATTEMPTS", "5"))
BLOCK_TIME = int(os.getenv("SIGNUP_BLOCK_TIME", "60"))  # minutes


def is_ip_blocked(ip: str) -> bool:
    """
    Check if an IP address is currently blocked.
    
    Args:
        ip: IP address to check
        
    Returns:
        True if IP is blocked, False otherwise
    """
    if ip in _blocked_ips:
        block_until = _blocked_ips[ip]
        current_time = time.time()
        
        if current_time < block_until:
            return True
        else:
            # Block expired, clean up
            del _blocked_ips[ip]
            if ip in _signup_attempts:
                del _signup_attempts[ip]
    
    return False


def get_retry_after(ip: str) -> int:
    """
    Get the number of minutes until an IP is unblocked.
    
    Args:
        ip: IP address to check
        
    Returns:
        Minutes until unblock, or 0 if not blocked
    """
    if ip in _blocked_ips:
        seconds_remaining = int(_blocked_ips[ip] - time.time())
        return max(1, seconds_remaining // 60)
    return 0


def record_failed_attempt(ip: str) -> bool:
    """
    Record a failed signup attempt for an IP address.
    Blocks the IP if it exceeds the maximum allowed attempts.
    
    Args:
        ip: IP address that failed signup
        
    Returns:
        True if IP was blocked, False otherwise
    """
    now = time.time()
    
    # Initialize attempts list for new IPs
    if ip not in _signup_attempts:
        _signup_attempts[ip] = []
    
    # Remove attempts older than 1 hour (sliding window)
    _signup_attempts[ip] = [
        attempt_time for attempt_time in _signup_attempts[ip]
        if now - attempt_time < 3600
    ]
    
    # Add current attempt
    _signup_attempts[ip].append(now)
    
    # Check if threshold exceeded
    attempt_count = len(_signup_attempts[ip])
    if attempt_count >= MAX_ATTEMPTS:
        block_until = now + (BLOCK_TIME * 60)
        _blocked_ips[ip] = block_until
        logger.warning(
            f"🚫 IP BLOCKED | IP: {ip} | Duration: {BLOCK_TIME} min | "
            f"Failed attempts: {attempt_count}"
        )
        return True
    
    logger.info(
        f"⚠️  Failed signup attempt | IP: {ip} | "
        f"Attempts: {attempt_count}/{MAX_ATTEMPTS}"
    )
    return False


def clear_attempts(ip: str):
    """
    Clear failed attempts for an IP (called on successful signup).
    
    Args:
        ip: IP address to clear
    """
    if ip in _signup_attempts:
        del _signup_attempts[ip]
    if ip in _blocked_ips:
        del _blocked_ips[ip]
    logger.info(f"✅ Cleared signup attempts for IP: {ip}")


def clear_ip_block(ip: str):
    """
    Manually clear IP block (for admin emergency use).
    
    Args:
        ip: IP address to unblock
    """
    cleared = False
    if ip in _blocked_ips:
        del _blocked_ips[ip]
        cleared = True
    if ip in _signup_attempts:
        del _signup_attempts[ip]
        cleared = True
    
    if cleared:
        logger.info(f"🔓 Manually cleared IP block: {ip}")
    else:
        logger.warning(f"⚠️  IP not found in block list: {ip}")


def get_blocked_ips() -> Dict[str, dict]:
    """
    Get all currently blocked IPs with their details.
    
    Returns:
        Dictionary of blocked IPs with block info
    """
    now = time.time()
    blocked_info = {}
    
    for ip, block_until in _blocked_ips.items():
        remaining_seconds = int(block_until - now)
        if remaining_seconds > 0:
            blocked_info[ip] = {
                "blocked_until": block_until,
                "remaining_minutes": remaining_seconds // 60,
                "attempt_count": len(_signup_attempts.get(ip, []))
            }
    
    return blocked_info


async def check_signup_protection(request: Request):
    """
    Middleware to check signup protection before processing request.
    Raises HTTPException if IP is blocked.
    
    Args:
        request: FastAPI request object
        
    Raises:
        HTTPException: 429 if IP is blocked
    """
    client_ip = get_real_ip(request)
    
    if is_ip_blocked(client_ip):
        retry_after = get_retry_after(client_ip)
        logger.warning(f"🚫 Blocked signup attempt from IP: {client_ip}")
        raise HTTPException(
            status_code=429,
            detail=f"Too many signup attempts. Please try again in {retry_after} minute(s).",
            headers={"Retry-After": str(retry_after * 60)}
        )


__all__ = [
    'is_ip_blocked',
    'get_retry_after',
    'record_failed_attempt',
    'clear_attempts',
    'clear_ip_block',
    'get_blocked_ips',
    'check_signup_protection'
]
