"""
Common error handlers and custom exceptions.
Provides centralized error handling across the application.
"""
import logging
from fastapi import HTTPException
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SmartHiringException(Exception):
    """Base exception for SmartHiring application"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(SmartHiringException):
    """Raised when validation fails"""
    pass


class AIServiceError(SmartHiringException):
    """Raised when AI service fails"""
    pass


class DatabaseError(SmartHiringException):
    """Raised when database operation fails"""
    pass


class FileProcessingError(SmartHiringException):
    """Raised when file processing fails"""
    pass


def handle_ai_error(error: Exception, fallback_value: Any = None) -> Any:
    """
    Handle AI service errors with fallback
    
    Args:
        error: The exception that occurred
        fallback_value: Value to return if error occurs
        
    Returns:
        Fallback value or raises exception
    """
    logger.error(f"AI Service Error: {error}")
    
    if fallback_value is not None:
        logger.info(f"Using fallback value: {fallback_value}")
        return fallback_value
    
    raise AIServiceError(f"AI service failed: {str(error)}")


def handle_database_error(error: Exception, operation: str = "database operation") -> None:
    """
    Handle database errors
    
    Args:
        error: The exception that occurred
        operation: Description of the operation that failed
        
    Raises:
        HTTPException with appropriate status code
    """
    logger.error(f"Database Error during {operation}: {error}")
    
    # Check for specific error types
    if "duplicate key" in str(error).lower() or "11000" in str(error):
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate entry: {operation} already exists"
        )
    
    raise HTTPException(
        status_code=500,
        detail=f"Database error during {operation}"
    )


def handle_file_error(error: Exception, filename: str = "file") -> None:
    """
    Handle file processing errors
    
    Args:
        error: The exception that occurred
        filename: Name of the file being processed
        
    Raises:
        HTTPException with appropriate status code
    """
    logger.error(f"File Processing Error for {filename}: {error}")
    
    if isinstance(error, HTTPException):
        raise error
    
    raise HTTPException(
        status_code=400,
        detail=f"Failed to process file {filename}: {str(error)}"
    )


def handle_validation_error(field: str, message: str) -> None:
    """
    Handle validation errors
    
    Args:
        field: Field that failed validation
        message: Validation error message
        
    Raises:
        HTTPException with 400 status code
    """
    logger.warning(f"Validation Error - {field}: {message}")
    
    raise HTTPException(
        status_code=400,
        detail=f"Validation failed for {field}: {message}"
    )


def safe_execute(func, *args, fallback=None, error_message="Operation failed", **kwargs):
    """
    Safely execute a function with error handling
    
    Args:
        func: Function to execute
        *args: Positional arguments for function
        fallback: Fallback value if function fails
        error_message: Custom error message
        **kwargs: Keyword arguments for function
        
    Returns:
        Function result or fallback value
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"{error_message}: {e}")
        if fallback is not None:
            return fallback
        raise
