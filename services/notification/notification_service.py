"""
Notification Service
Centralized service for creating and managing notifications
"""
from datetime import datetime, timezone
from bson import ObjectId
from typing import Optional, Dict, Any
from utils import logger


async def insert_notification_db(
    db, 
    user_id: str, 
    title: str, 
    message: str, 
    notification_type: str = 'info', 
    link: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create a notification for a user (Async)
    
    Args:
        db: Database connection
        user_id: User ID to send notification to
        title: Notification title
        message: Notification message
        notification_type: Type of notification ('info', 'success', 'warning', 'error')
        link: Optional link to navigate to when clicked
        metadata: Optional additional data
        
    Returns:
        str: Notification ID
    """
    try:
        notification = {
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": notification_type,
            "link": link,
            "metadata": metadata or {},
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        result = await db.notifications.insert_one(notification)
        notification_id = str(result.inserted_id)
        
        logger.info(f"Created persistent notification {notification_id} for user {user_id}")
        
        # Fire-and-forget socket emission
        # We do this AFTER DB write to ensure persistence
        # In a real event bus, this might be a separate handler, but here we emit directly for latency
        from app.proctoring.socketio_server import send_notification_to_user
        import asyncio
        
        notification['id'] = notification_id
        notification['_id'] = str(notification_id) # Ensure serialization
        
        # Use asyncio.create_task to not block the request
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(send_notification_to_user(user_id, notification))
        except RuntimeError:
             pass # No loop running (e.g. during tests)

        return notification_id
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")
        raise


async def create_application_notification(db, recruiter_id: str, job_title: str, candidate_name: str, job_id: str):
    """Create notification when a candidate applies to a job (Async)"""
    return await create_notification(
        db=db,
        user_id=recruiter_id,
        title="New Job Application",
        message=f"{candidate_name} has applied to your job: {job_title}",
        notification_type="info",
        link=f"/dashboard/candidates?job_id={job_id}"
    )


async def create_status_change_notification(
    db, 
    candidate_email: str, 
    job_title: str, 
    new_status: str,
    user_id: Optional[str] = None
):
    """Create notification when candidate status changes (Async)"""
    # If user_id not provided, try to find it from email
    if not user_id:
        return None
    
    status_messages = {
        "Interview": f"Great news! You've been shortlisted for an interview for {job_title}",
        "Hired": f"Congratulations! You've been selected for {job_title}",
        "Rejected": f"Thank you for applying to {job_title}. We've moved forward with other candidates."
    }
    
    message = status_messages.get(new_status, f"Your application status for {job_title} has been updated to {new_status}")
    
    notification_type = {
        "Interview": "info",
        "Hired": "success",
        "Rejected": "warning"
    }.get(new_status, "info")
    
    return await create_notification(
        db=db,
        user_id=user_id,
        title="Application Status Update",
        message=message,
        notification_type=notification_type,
        link="/applications"
    )


async def create_job_deadline_notification(db, recruiter_id: str, job_title: str, days_remaining: int):
    """Create notification when job deadline is approaching (Async)"""
    return await create_notification(
        db=db,
        user_id=recruiter_id,
        title="Job Deadline Approaching",
        message=f"Your job posting '{job_title}' will close in {days_remaining} day{'s' if days_remaining != 1 else ''}",
        notification_type="warning",
        link="/dashboard/jobs"
    )


async def get_user_notifications(db, user_id: str, limit: int = 10, offset: int = 0):
    """Get notifications for a user (Async)"""
    cursor = db.notifications.find({
        "user_id": user_id
    }).sort("created_at", -1).skip(offset).limit(limit)
    
    notifications = await cursor.to_list(length=limit)
    for notif in notifications:
        notif["id"] = str(notif.pop("_id"))
    
    unread_count = await db.notifications.count_documents({
        "user_id": user_id,
        "is_read": False
    })
    
    return notifications, unread_count


async def mark_notification_read(db, notification_id: str, user_id: str) -> bool:
    """Mark a notification as read (Async)"""
    result = await db.notifications.update_one(
        {"_id": ObjectId(notification_id), "user_id": user_id},
        {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()}}
    )
    return result.matched_count > 0


async def mark_all_read(db, user_id: str) -> bool:
    """Mark all notifications as read for a user (Async)"""
    result = await db.notifications.update_many(
        {"user_id": user_id, "is_read": False},
        {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()}}
    )
    return result.modified_count > 0

async def delete_notification(db, notification_id: str, user_id: str) -> bool:
    """Delete a notification for a user (Async)"""
    result = await db.notifications.delete_one(
        {"_id": ObjectId(notification_id), "user_id": user_id}
    )
    return result.deleted_count > 0

async def create_notification(
    db, 
    user_id: str, 
    title: str, 
    message: str, 
    notification_type: str = 'info', 
    link: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Unified notification creator (Async)
    Uses NotificationManager for complex logic (Email + Preferences)
    """
    from .notification_manager import NotificationManager
    
    # Initialize Manager
    manager = NotificationManager(db)
    
    # Determine implied type from title/message
    category = 'system'
    title_lower = title.lower()
    if 'application' in title_lower:
        category = 'application'
    elif 'interview' in title_lower:
        category = 'interview'
    elif 'job' in title_lower:
        category = 'job'
    
    # Call manager.send (now native async)
    result = await manager.send(
        user_id=user_id,
        type=category,
        title=title,
        message=message,
        link=link,
        metadata=metadata,
        channels=['email', 'in_app']
    )
    
    return result.get('in_app', {}).get('id', 'pending')

