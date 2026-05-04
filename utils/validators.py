"""
Security Validators
Prevents NoSQL injection and validates user inputs
"""
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from typing import Optional, List


def validate_object_id(id_string: str, field_name: str = "ID") -> ObjectId:
    """
    Safely validate and convert string to ObjectId.
    Prevents NoSQL injection attacks.
    
    Args:
        id_string: String representation of ObjectId
        field_name: Name of field for error messages
        
    Returns:
        Valid ObjectId
        
    Raises:
        HTTPException: If ID format is invalid
    """
    if not id_string:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required"
        )
    
    # Check for suspicious patterns (NoSQL injection attempts)
    if isinstance(id_string, dict) or isinstance(id_string, list):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format"
        )
    
    try:
        return ObjectId(id_string)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Must be a valid 24-character hex string."
        )


def validate_object_ids(id_strings: List[str], field_name: str = "IDs") -> List[ObjectId]:
    """
    Validate multiple ObjectIds
    
    Args:
        id_strings: List of ObjectId strings
        field_name: Name of field for error messages
        
    Returns:
        List of valid ObjectIds
    """
    if not id_strings:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} list cannot be empty"
        )
    
    return [validate_object_id(id_str, field_name) for id_str in id_strings]


def sanitize_query_input(value: any) -> any:
    """
    Sanitize user input to prevent NoSQL injection in query parameters
    
    Args:
        value: User input value
        
    Returns:
        Sanitized value
    """
    # Reject dict/list inputs that could be NoSQL operators
    if isinstance(value, (dict, list)):
        raise HTTPException(
            status_code=400,
            detail="Invalid input format"
        )
    
    return value


def validate_email(email: str) -> str:
    """
    Validate email format
    
    Args:
        email: Email address
        
    Returns:
        Lowercase email
    """
    import re
    
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    email = email.strip().lower()
    
    # Basic email validation
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    return email


def validate_pagination(page: int, per_page: int, max_per_page: int = 100) -> tuple:
    """
    Validate pagination parameters
    
    Args:
        page: Page number (1-indexed)
        per_page: Items per page
        max_per_page: Maximum allowed items per page
        
    Returns:
        Tuple of (validated_page, validated_per_page)
    """
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be >= 1")
    
    if per_page < 1:
        raise HTTPException(status_code=400, detail="Per page must be >= 1")
    
    if per_page > max_per_page:
        raise HTTPException(
            status_code=400,
            detail=f"Per page cannot exceed {max_per_page}"
        )
    
    return page, per_page
