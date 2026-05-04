"""
Database Helper Functions
Utility functions for common database operations
"""
from typing import Optional, Dict, Any, List
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.collection import Collection
from pymongo.cursor import Cursor

from .exceptions import NotFoundError, ValidationError


def safe_object_id(id_str: str) -> Optional[ObjectId]:
    """
    Safely convert string to ObjectId
    
    Args:
        id_str: String representation of ObjectId
        
    Returns:
        ObjectId if valid, None otherwise
    """
    if not id_str:
        return None
        
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None


def get_document_or_404(
    collection: Collection,
    document_id: str,
    owner_id: Optional[str] = None,
    error_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a document by ID or raise 404 error
    
    Args:
        collection: MongoDB collection
        document_id: Document ID to find
        owner_id: Optional owner ID for authorization check
        error_message: Custom error message
        
    Returns:
        Document dictionary
        
    Raises:
        NotFoundError: If document not found or unauthorized
    """
    # Convert to ObjectId
    obj_id = safe_object_id(document_id)
    if not obj_id:
        raise NotFoundError(
            error_message or f"Invalid {collection.name[:-1]} ID"
        )
    
    # Build query
    query = {"_id": obj_id}
    if owner_id:
        # Add owner check
        owner_obj_id = safe_object_id(owner_id)
        if not owner_obj_id:
            raise ValidationError("Invalid owner ID")
        query["user_id"] = owner_obj_id
    
    # Find document
    document = collection.find_one(query)
    
    if not document:
        if owner_id:
            raise NotFoundError(
                error_message or f"{collection.name[:-1].title()} not found or unauthorized"
            )
        else:
            raise NotFoundError(
                error_message or f"{collection.name[:-1].title()} not found"
            )
    
    return document


def get_documents_batch(
    collection: Collection,
    document_ids: List[str],
    owner_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get multiple documents by IDs
    
    Args:
        collection: MongoDB collection
        document_ids: List of document IDs
        owner_id: Optional owner ID for authorization
        
    Returns:
        List of documents
    """
    # Convert to ObjectIds
    obj_ids = [safe_object_id(id_str) for id_str in document_ids]
    obj_ids = [oid for oid in obj_ids if oid is not None]
    
    if not obj_ids:
        return []
    
    # Build query
    query = {"_id": {"$in": obj_ids}}
    if owner_id:
        owner_obj_id = safe_object_id(owner_id)
        if owner_obj_id:
            query["user_id"] = owner_obj_id
    
    # Find documents
    documents = list(collection.find(query))
    
    return documents


def paginate_query(
    cursor: Cursor,
    page: int = 1,
    page_size: int = 10,
    max_page_size: int = 100
) -> Dict[str, Any]:
    """
    Paginate a MongoDB cursor
    
    Args:
        cursor: MongoDB cursor
        page: Page number (1-indexed)
        page_size: Number of items per page
        max_page_size: Maximum allowed page size
        
    Returns:
        Dictionary with pagination metadata and results
    """
    # Validate inputs
    page = max(1, page)
    page_size = min(max(1, page_size), max_page_size)
    
    # Calculate skip
    skip = (page - 1) * page_size
    
    # Get total count
    total = cursor.collection.count_documents(cursor._Cursor__spec or {})
    
    # Get paginated results
    results = list(cursor.skip(skip).limit(page_size))
    
    # Calculate metadata
    total_pages = (total + page_size - 1) // page_size
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "results": results,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": has_next,
            "has_prev": has_prev
        }
    }


async def get_document_or_404_async(
    collection,
    document_id: str,
    owner_id: Optional[str] = None,
    error_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a document by ID or raise 404 error (Async)
    """
    obj_id = safe_object_id(document_id)
    if not obj_id:
        raise NotFoundError(error_message or f"Invalid {collection.name[:-1]} ID")
    
    query = {"_id": obj_id}
    if owner_id:
        owner_obj_id = safe_object_id(owner_id)
        if not owner_obj_id:
            raise ValidationError("Invalid owner ID")
        query["user_id"] = owner_obj_id
    
    document = await collection.find_one(query)
    
    if not document:
        raise NotFoundError(error_message or f"{collection.name[:-1].title()} not found")
    
    return document


async def get_documents_batch_async(
    collection,
    document_ids: List[str],
    owner_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get multiple documents by IDs (Async)
    """
    obj_ids = [safe_object_id(id_str) for id_str in document_ids]
    obj_ids = [oid for oid in obj_ids if oid is not None]
    
    if not obj_ids:
        return []
    
    query = {"_id": {"$in": obj_ids}}
    if owner_id:
        owner_obj_id = safe_object_id(owner_id)
        if owner_obj_id:
            query["user_id"] = owner_obj_id
    
    return await collection.find(query).to_list(length=len(obj_ids))


__all__ = [
    "safe_object_id",
    "get_document_or_404",
    "get_document_or_404_async",
    "get_documents_batch",
    "get_documents_batch_async",
    "paginate_query"
]
