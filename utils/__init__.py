"""
Utility Package
Common helper functions and utilities
"""
from .db_helpers import (
    get_document_or_404,
    get_document_or_404_async,
    get_documents_batch,
    get_documents_batch_async,
    safe_object_id,
    paginate_query
)
from .cache import (
    Cache,
    get_cache,
    cached,
    invalidate_cache
)
from .logger import (
    AppLogger,
    get_logger,
    logger
)
from .exceptions import (
    AppException,
    NotFoundError,
    ForbiddenError,
    UnauthorizedError,
    ValidationError,
    ConflictError,
    RateLimitError,
    ExternalServiceError
)
from .db import get_db, get_db_sync, get_client

__all__ = [
    # Database helpers
    "get_document_or_404",
    "get_document_or_404_async",
    "get_documents_batch",
    "get_documents_batch_async",
    "safe_object_id",
    "paginate_query",
    # Cache
    "Cache",
    "get_cache",
    "cached",
    "invalidate_cache",
    # Logger
    "AppLogger",
    "get_logger",
    "logger",
    # Exceptions
    "AppException",
    "NotFoundError",
    "ForbiddenError",
    "UnauthorizedError",
    "ValidationError",
    "ConflictError",
    "RateLimitError",
    "ExternalServiceError",
    # DB Connection
    "get_db",
    "get_db_sync",
    "get_client"
]
