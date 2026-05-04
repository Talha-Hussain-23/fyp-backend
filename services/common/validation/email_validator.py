"""
Email validation utilities.
Validates email format and domain.
"""
import re
from typing import Tuple


def validate_email(email: str) -> Tuple[bool, str]:
    """
    Validate email address format
    
    Args:
        email: Email address to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not email:
        return False, "Email is required"
    
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return False, "Invalid email format"
    
    # Check for common typos
    if '..' in email:
        return False, "Email contains consecutive dots"
    
    if email.startswith('.') or email.endswith('.'):
        return False, "Email cannot start or end with a dot"
    
    # Check domain
    domain = email.split('@')[1]
    if '.' not in domain:
        return False, "Invalid email domain"
    
    return True, ""


def is_valid_email(email: str) -> bool:
    """
    Check if email is valid (simple boolean check)
    
    Args:
        email: Email address to validate
        
    Returns:
        True if valid, False otherwise
    """
    is_valid, _ = validate_email(email)
    return is_valid


def normalize_email(email: str) -> str:
    """
    Normalize email address (lowercase, trim)
    
    Args:
        email: Email address to normalize
        
    Returns:
        Normalized email address
    """
    if not email:
        return ""
    
    return email.strip().lower()


def extract_domain(email: str) -> str:
    """
    Extract domain from email address
    
    Args:
        email: Email address
        
    Returns:
        Domain part of email
    """
    if not email or '@' not in email:
        return ""
    
    return email.split('@')[1].lower()
