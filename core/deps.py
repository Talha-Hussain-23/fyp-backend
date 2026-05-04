"""
Core Dependencies (Dependency Injection)
Centralizes database access patterns.
"""

from fastapi import Request
from typing import Generator, Any
from utils.db import get_db as get_db_generator

# For type hinting without runtime import issues
# from pymongo.database import Database

def get_db(request: Request):
    """
    Get database from app state (Legacy/Simple).
    For truly robust DI, we prefer the generator approach below.
    """
    return request.app.state.db

def get_db_session() -> Generator:
    """
    Yields a database session from the connection pool.
    Usage: db: Database = Depends(get_db_session)
    """
    return get_db_generator()
