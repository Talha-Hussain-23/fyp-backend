"""Common error handling utilities."""

from .handlers import (
    SmartHiringException,
    ValidationError,
    AIServiceError,
    DatabaseError,
    FileProcessingError,
    handle_ai_error,
    handle_database_error,
    handle_file_error,
    handle_validation_error,
    safe_execute,
)

__all__ = [
    'SmartHiringException',
    'ValidationError',
    'AIServiceError',
    'DatabaseError',
    'FileProcessingError',
    'handle_ai_error',
    'handle_database_error',
    'handle_file_error',
    'handle_validation_error',
    'safe_execute',
]
