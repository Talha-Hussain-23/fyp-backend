"""
Notification Routes
Handle in-app notifications and user preferences
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Dict, Any, List
from core.auth import get_current_user
from utils.db import get_db
from bson import ObjectId
from services.notification.notification_service import (
    get_user_notifications, 
    mark_notification_read, 
    mark_all_read
)
from pydantic import BaseModel

router = APIRouter()

class NotificationPreferenceUpdate(BaseModel):
    email_enabled: bool = True
    in_app_enabled: bool = True
    categories: Dict[str, bool] = {}

@router.get("", response_model=Dict[str, Any])
async def get_notifications(
    limit: int = 20, 
    offset: int = 0, 
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user notifications with pagination"""
    notifications, unread_count = await get_user_notifications(db, current_user.id, limit, offset)
    
    return {
        "success": True,
        "notifications": notifications,
        "unread_count": unread_count
    }

@router.put("/mark-all-read")
async def mark_all_as_read(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Mark all notifications as read"""
    await mark_all_read(db, current_user.id)
    return {"success": True, "message": "All notifications marked as read"}

@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Mark a specific notification as read"""
    success = await mark_notification_read(db, notification_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"success": True, "message": "Notification marked as read"}

@router.delete("/{notification_id}")
async def delete_notif(
    notification_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete a specific notification"""
    from services.notification.notification_service import delete_notification
    success = await delete_notification(db, notification_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"success": True, "message": "Notification deleted successfully"}

@router.get("/preferences")
async def get_preferences(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user notification preferences"""
    user = await db.users.find_one({"_id": ObjectId(current_user.id)})
    if not user:
         raise HTTPException(status_code=404, detail="User not found")
         
    prefs = user.get("notification_preferences", {
        "email_enabled": True,
        "in_app_enabled": True,
        "categories": {
            "applications": True,
            "interviews": True,
            "job_updates": True,
            "system": True
        }
    })
    return {"success": True, "preferences": prefs}

@router.put("/preferences")
async def update_preferences(
    preferences: NotificationPreferenceUpdate,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update user notification preferences"""
    await db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"notification_preferences": preferences.dict()}}
    )
    return {"success": True, "message": "Preferences updated successfully", "preferences": preferences}
