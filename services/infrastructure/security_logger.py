"""
Security Event Logger
Logs security-relevant events for audit and monitoring
"""
from core.logging_service import logger
from datetime import datetime, timezone
from typing import Optional, Dict, Any


def log_security_event(
    event_type: str,
    user_id: Optional[str],
    details: Dict[str, Any],
    request=None,
    severity: str = "WARNING"
):
    """
    Log security-relevant events to database and application logs
    
    Args:
        event_type: Type of security event (failed_login, unauthorized_access, etc.)
        user_id: User ID involved (if applicable)
        details: Additional event details
        request: FastAPI Request object (for IP/user-agent)
        severity: Log severity (INFO, WARNING, ERROR, CRITICAL)
    """
    from utils.db import get_db_sync
    
    try:
        db = get_db_sync()
        
        event = {
            "event_type": event_type,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc),
            "details": details,
            "ip_address": request.client.host if request else None,
            "user_agent": request.headers.get("user-agent") if request else None,
            "severity": severity
        }
        
        # Store in database
        db.security_events.insert_one(event)
        
        # Also log to application logs
        log_message = f"Security Event: {event_type} - User: {user_id or 'Unknown'} - IP: {event.get('ip_address', 'Unknown')}"
        
        if severity == "CRITICAL":
            logger.critical(log_message, extra=details)
        elif severity == "ERROR":
            logger.error(log_message, extra=details)
        elif severity == "WARNING":
            logger.warning(log_message, extra=details)
        else:
            logger.info(log_message, extra=details)
            
    except Exception as e:
        # Don't fail the request if logging fails
        logger.error(f"Failed to log security event: {e}")


def log_failed_login(email: str, reason: str, request=None):
    """Log failed login attempt"""
    log_security_event(
        "failed_login",
        email,
        {"reason": reason},
        request,
        severity="WARNING"
    )


def log_unauthorized_access(user_id: str, resource_type: str, resource_id: str, request=None):
    """Log unauthorized access attempt"""
    log_security_event(
        "unauthorized_access",
        user_id,
        {
            "resource_type": resource_type,
            "resource_id": resource_id
        },
        request,
        severity="ERROR"
    )


def log_suspicious_activity(user_id: str, activity: str, details: Dict[str, Any], request=None):
    """Log suspicious activity"""
    log_security_event(
        "suspicious_activity",
        user_id,
        {"activity": activity, **details},
        request,
        severity="WARNING"
    )


def log_account_lockout(user_id: str, reason: str, request=None):
    """Log account lockout"""
    log_security_event(
        "account_lockout",
        user_id,
        {"reason": reason},
        request,
        severity="WARNING"
    )


def log_password_change(user_id: str, method: str, request=None):
    """Log password change"""
    log_security_event(
        "password_change",
        user_id,
        {"method": method},
        request,
        severity="INFO"
    )


def log_permission_escalation_attempt(user_id: str, attempted_action: str, request=None):
    """Log permission escalation attempt"""
    log_security_event(
        "permission_escalation_attempt",
        user_id,
        {"attempted_action": attempted_action},
        request,
        severity="CRITICAL"
    )
