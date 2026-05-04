from datetime import datetime, timezone
from typing import Dict, Any, Optional
from bson import ObjectId
from utils import get_db, logger

COLLECTION_NAME = "audit_logs"

def log_action(
    user_id: str,
    action: str,
    target_collection: str,
    target_id: str,
    changes: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Log a critical system action to the database.
    
    Args:
        user_id: ID of the user performing the action
        action: Description of action (e.g., "UPDATE_JOB", "DELETE_CANDIDATE")
        target_collection: Collection being modified
        target_id: ID of the document being modified
        changes: Dictionary of specific field changes (optional)
        metadata: Extra context like IP address, user agent, etc. (optional)
        
    Returns:
        str: ID of the created log entry
    """
    try:
        db = next(get_db())
        
        log_entry = {
            "user_id": user_id,
            "action": action,
            "target_collection": target_collection,
            "target_id": str(target_id),
            "changes": changes or {},
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }
        
        result = db[COLLECTION_NAME].insert_one(log_entry)
        log_id = str(result.inserted_id)
        
        logger.info(f"📝 Audit Log: {action} on {target_collection}:{target_id} by {user_id}")
        return log_id

    except Exception as e:
        logger.error(f"❌ Failed to write audit log: {e}")
        # We don't want audit logging failure to crash the main application flow
        # so we catch and log error, but return None
        return None

def get_audit_logs(
    target_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50
):
    """Retrieve audit logs with optional filtering"""
    try:
        db = next(get_db())
        query = {}
        
        if target_id:
            query["target_id"] = str(target_id)
        if user_id:
            query["user_id"] = user_id
            
        logs = list(db[COLLECTION_NAME].find(query).sort("timestamp", -1).limit(limit))
        
        # Serialize ObjectIds
        for log in logs:
            log["_id"] = str(log["_id"])
            
        return logs
    except Exception as e:
        logger.error(f"Error fetching audit logs: {e}")
        return []
