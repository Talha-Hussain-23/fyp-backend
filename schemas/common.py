"""
Shared Pydantic Schemas
Common models used across multiple modules
"""
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class APIResponse(BaseModel):
    """Standard API response structure."""
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None
    error: Optional[dict] = None


class PaginatedResponse(APIResponse):
    """Paginated list response."""
    page: int
    per_page: int
    total: int
    total_pages: int
    items: List[Any]
