"""
Email Validation Utility
Validates email addresses before sending
"""
import re

def is_valid_email(email: str) -> bool:
    """
    Validate email address format and domain
    Returns True if email is valid, False otherwise
    """
    if not email:
        return False
    
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return False
    
    # Check for invalid test domains
    invalid_domains = ['test.com', 'example.com', 'localhost', 'invalid.com']
    domain = email.split('@')[1].lower()
    
    if domain in invalid_domains:
        return False
    
    return True

def validate_email_or_raise(email: str, field_name: str = "Email"):
    """
    Validate email and raise exception if invalid
    """
    from fastapi import HTTPException
    
    if not email:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required"
        )
    
    if not is_valid_email(email):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name.lower()}: '{email}'. Please use a valid email address with a real domain (not test.com or example.com)."
        )
    
    return email
