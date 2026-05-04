"""
Enhanced Notification Service
Centralized notification creation with proper routing
"""
from datetime import datetime, timezone
from typing import Optional
from utils import logger

# Notification categories with metadata
NOTIFICATION_CATEGORIES = {
    "application": {
        "icon": "📄",
        "color": "#4CAF50",
        "priority": "medium"
    },
    "interview": {
        "icon": "🎯",
        "color": "#2196F3",
        "priority": "high"
    },
    "reclaim": {
        "icon": "🔄",
        "color": "#FF9800",
        "priority": "high"
    },
    "status": {
        "icon": "📊",
        "color": "#9C27B0",
        "priority": "low"
    },
    "system": {
        "icon": "🔔",
        "color": "#666",
        "priority": "medium"
    }
}

def create_notification(
    db,
    user_id: str,
    category: str,
    title: str,
    message: str,
    link: Optional[str] = None,
    metadata: Optional[dict] = None
):
    """
    Create a notification with proper categorization
    
    Args:
        db: Database connection
        user_id: Recipient user ID
        category: Notification category (application/interview/reclaim/status/system)
        title: Notification title
        message: Notification message
        link: Optional link to relevant page
        metadata: Optional additional data
    
    Returns:
        notification_id: ID of created notification
    """
    try:
        category_info = NOTIFICATION_CATEGORIES.get(category, NOTIFICATION_CATEGORIES["system"])
        
        notification = {
            "user_id": user_id,
            "category": category,
            "type": category,  # For backward compatibility
            "title": title,
            "message": message,
            "link": link,
            "icon": category_info.get("icon", "🔔"),
            "color": category_info.get("color", "#666"),
            "priority": category_info.get("priority", "medium"),
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        result = db.notifications.insert_one(notification)
        
        logger.info(f"Notification created: {category} for user {user_id}")
        
        # Real-time updates handled via frontend polling
        # socketio.emit('new_notification', notification, room=user_id)
        
        return str(result.inserted_id)
        
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")
        return None

# Convenience functions for common notifications

def notify_new_application(db, recruiter_id: str, candidate_name: str, job_title: str, application_id: str):
    """Notify recruiter of new application"""
    return create_notification(
        db=db,
        user_id=recruiter_id,
        category="application",
        title="New Application Received",
        message=f"{candidate_name} applied for {job_title}",
        link=f"/applications/{application_id}",
        metadata={"application_id": application_id}
    )

def notify_interview_scheduled(db, candidate_user_id: str, job_title: str, interview_id: str):
    """Notify candidate of interview invitation"""
    return create_notification(
        db=db,
        user_id=candidate_user_id,
        category="interview",
        title="Interview Invitation",
        message=f"You've been invited to interview for {job_title}",
        link=f"/interview/{interview_id}",
        metadata={"interview_id": interview_id}
    )

def notify_interview_completed(db, recruiter_id: str, candidate_name: str, interview_id: str, final_score: float):
    """Notify recruiter of completed interview"""
    return create_notification(
        db=db,
        user_id=recruiter_id,
        category="interview",
        title="Interview Completed",
        message=f"{candidate_name} completed interview (Score: {final_score}/10)",
        link=f"/interviews/{interview_id}",
        metadata={"interview_id": interview_id, "score": final_score}
    )

def notify_reclaim_request(db, recruiter_id: str, candidate_name: str, job_title: str, reclaim_id: str):
    """Notify recruiter of reclaim request"""
    return create_notification(
        db=db,
        user_id=recruiter_id,
        category="reclaim",
        title="Interview Reclaim Request",
        message=f"{candidate_name} requested to reclaim interview for {job_title}",
        link=f"/reclaim-requests/{reclaim_id}",
        metadata={"reclaim_id": reclaim_id}
    )

def notify_reclaim_approved(db, candidate_user_id: str, job_title: str, new_interview_id: str):
    """Notify candidate of approved reclaim"""
    return create_notification(
        db=db,
        user_id=candidate_user_id,
        category="reclaim",
        title="Interview Reclaim Approved",
        message=f"Your reclaim request for {job_title} has been approved",
        link=f"/interview/{new_interview_id}",
        metadata={"interview_id": new_interview_id}
    )

def notify_reclaim_rejected(db, candidate_user_id: str, job_title: str, reason: str):
    """Notify candidate of rejected reclaim"""
    return create_notification(
        db=db,
        user_id=candidate_user_id,
        category="reclaim",
        title="Interview Reclaim Rejected",
        message=f"Your reclaim request for {job_title} was not approved",
        link="/reclaim",
        metadata={"reason": reason}
    )

def notify_status_update(db, candidate_user_id: str, job_title: str, new_status: str):
    """Notify candidate of application status change"""
    return create_notification(
        db=db,
        user_id=candidate_user_id,
        category="status",
        title="Application Status Updated",
        message=f"Your application for {job_title} is now: {new_status}",
        link="/applications",
        metadata={"status": new_status}
    )
