"""
Optimistic Locking Middleware
Provides version-based concurrency control for MongoDB documents
"""

from typing import Dict, Any, Optional
from bson import ObjectId
from pymongo.database import Database
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

class OptimisticLockError(HTTPException):
    """Raised when a document has been modified by another process"""
    def __init__(self, message: str = "Document was modified by another process"):
        super().__init__(status_code=409, detail=message)

class VersionedDocument:
    """Helper class for managing document versions"""
    
    @staticmethod
    def add_version(document: Dict[str, Any]) -> Dict[str, Any]:
        """Add version field to a new document"""
        if "version" not in document:
            document["version"] = 1
        return document
    
    @staticmethod
    def update_with_version(
        db: Database,
        collection_name: str,
        document_id: str,
        current_version: int,
        update_data: Dict[str, Any],
        increment_fields: Optional[Dict[str, int]] = None
    ) -> bool:
        """
        Update document with optimistic locking
        
        Args:
            db: MongoDB database instance
            collection_name: Name of the collection
            document_id: Document ID
            current_version: Expected current version
            update_data: Fields to update
            increment_fields: Fields to increment (optional)
            
        Returns:
            True if update succeeded
            
        Raises:
            OptimisticLockError: If version mismatch detected
        """
        try:
            collection = db[collection_name]
            
            # Build update operation
            update_op = {
                "$set": {**update_data},
                "$inc": {"version": 1}
            }
            
            # Add increment fields if provided
            if increment_fields:
                update_op["$inc"].update(increment_fields)
            
            # Perform update with version check
            result = collection.update_one(
                {
                    "_id": ObjectId(document_id),
                    "version": current_version
                },
                update_op
            )
            
            if result.matched_count == 0:
                # Check if document exists
                doc = collection.find_one({"_id": ObjectId(document_id)})
                
                if not doc:
                    raise HTTPException(404, "Document not found")
                
                # Version mismatch
                raise OptimisticLockError(
                    f"Document version mismatch. Expected {current_version}, "
                    f"but current version is {doc.get('version', 'unknown')}"
                )
            
            return result.modified_count > 0
            
        except OptimisticLockError:
            raise
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in versioned update: {e}")
            raise HTTPException(500, f"Update failed: {str(e)}")
    
    @staticmethod
    def get_with_version(
        db: Database,
        collection_name: str,
        document_id: str
    ) -> tuple[Dict[str, Any], int]:
        """
        Get document with its current version
        
        Returns:
            Tuple of (document, version)
        """
        try:
            collection = db[collection_name]
            doc = collection.find_one({"_id": ObjectId(document_id)})
            
            if not doc:
                raise HTTPException(404, "Document not found")
            
            version = doc.get("version", 1)
            return doc, version
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting document: {e}")
            raise HTTPException(500, f"Failed to get document: {str(e)}")
    
    @staticmethod
    def initialize_version(db: Database, collection_name: str):
        """
        Add version field to all documents in a collection that don't have it
        
        Use this for migrating existing collections
        """
        try:
            collection = db[collection_name]
            
            # Update all documents without version field
            result = collection.update_many(
                {"version": {"$exists": False}},
                {"$set": {"version": 1}}
            )
            
            logger.info(
                f"Initialized version for {result.modified_count} documents "
                f"in {collection_name}"
            )
            
            return result.modified_count
            
        except Exception as e:
            logger.error(f"Error initializing versions: {e}")
            raise

# Example usage functions

def update_job_with_lock(
    db: Database,
    job_id: str,
    current_version: int,
    update_data: Dict[str, Any]
) -> bool:
    """Update job with optimistic locking"""
    return VersionedDocument.update_with_version(
        db, "jds", job_id, current_version, update_data
    )

def update_application_with_lock(
    db: Database,
    app_id: str,
    current_version: int,
    update_data: Dict[str, Any]
) -> bool:
    """Update application with optimistic locking"""
    return VersionedDocument.update_with_version(
        db, "applications", app_id, current_version, update_data
    )

def update_interview_with_lock(
    db: Database,
    interview_id: str,
    current_version: int,
    update_data: Dict[str, Any],
    increment_fields: Optional[Dict[str, int]] = None
) -> bool:
    """Update interview with optimistic locking"""
    return VersionedDocument.update_with_version(
        db, "interviews", interview_id, current_version, 
        update_data, increment_fields
    )
