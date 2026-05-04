"""
Recruiter Routes
Endpoints for recruiter-specific functionality like emails and notifications
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from typing import Optional

from utils import (
    get_db, 
    logger,
    ForbiddenError
)
from core.auth import get_current_user

router = APIRouter()

@router.get("/emails-and-notifications")
async def get_recruiter_emails_and_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    job_id: Optional[str] = None,
    type_filter: Optional[str] = None,
    search: Optional[str] = None,
    unread_only: bool = False,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get emails and notifications for the current recruiter's jobs"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can access this endpoint")
    
    try:
        # 1. Get recruiter's jobs & build job map
        job_map = {}
        job_ids = []
        async for job in db.jds.find({"recruiter_id": current_user.id}, {"title": 1}):
            jid_str = str(job["_id"])
            job_map[jid_str] = job.get("title", "Untitled")
            job_ids.append(jid_str)
        
        # 2. Build queries
        email_query = {"recruiter_id": current_user.id}
        notif_query = {"user_id": current_user.id} # Recruiter gets their own notifications
        
        if job_id:
            email_query["job_id"] = job_id
            # Note: Notifications might have job_id in metadata or separate field
            # For simplicity, we filter by recruiter's notification stream
            
        if search:
            email_query["$or"] = [
                {"subject": {"$regex": search, "$options": "i"}},
                {"to": {"$regex": search, "$options": "i"}}
            ]
            notif_query["$or"] = [
                {"title": {"$regex": search, "$options": "i"}},
                {"message": {"$regex": search, "$options": "i"}}
            ]
            
        if type_filter:
            # Map frontend types to backend templates and categories
            if type_filter == "application":
                email_query["template"] = "application_submitted"
                notif_query["$or"] = notif_query.get("$or", []) + [{"title": {"$regex": "application", "$options": "i"}}]
            elif type_filter == "interview":
                email_query["template"] = {"$in": ["interview_invite", "interview_reminder", "reclaim_approved"]}
                notif_query["$or"] = notif_query.get("$or", []) + [{"title": {"$regex": "interview", "$options": "i"}}]
            elif type_filter == "evaluation":
                email_query["template"] = {"$in": ["result_selected", "result_rejected"]}
                notif_query["$or"] = notif_query.get("$or", []) + [{"title": {"$regex": "eval|score|result", "$options": "i"}}]
            elif type_filter == "system":
                email_query["template"] = {"$in": ["recruiter_announcement", "cheating_warning", "cheating_disqualification"]}
                notif_query["type"] = "system"
                
        if unread_only:
            notif_query["is_read"] = False
            # Emails don't have a read status for recruiters in this context, so if unread_only is checked,
            # we typically only want to show unread notifications. We can force email_query to return nothing.
            email_query["_id"] = "force_empty"
        # 3. Fetch Data (Parallel for efficiency)
        import asyncio
        from services.notification.notification_service import get_user_notifications
        
        # Fetch emails
        email_cursor = await db.email_logs.find(email_query).sort("sentAt", -1).skip((page-1)*limit).limit(limit).to_list(length=limit)
        
        # Fetch notifications using the constructed query
        notif_cursor = await db.notifications.find(notif_query).sort("created_at", -1).skip((page-1)*limit).limit(limit).to_list(length=limit)
        notifs = notif_cursor
        for notif in notifs:
            if "_id" in notif:
                notif["id"] = str(notif.pop("_id"))
                
        # Count unread specifically for the current filtered view
        unread_query = {**notif_query, "is_read": False}
        unread_count = await db.notifications.count_documents(unread_query)
        
        # 4. Enrich & Serialize Data
        sanitized_emails = []
        for email in email_cursor:
            # Pop _id and convert to id string
            eid = str(email.pop("_id"))
            jid = email.get("job_id")
            sanitized_emails.append({
                **email,
                "id": eid,
                "job_id": str(jid) if jid else None,
                "job_title": job_map.get(str(jid), "General") if jid else "General"
            })
            
        sanitized_notifs = []
        for notif in notifs:
            # get_user_notifications already pops _id into id
            jid = notif.get("job_id") or notif.get("metadata", {}).get("job_id")
            sanitized_notifs.append({
                **notif,
                "job_id": str(jid) if jid else None,
                "job_title": job_map.get(str(jid), "System") if jid else "System"
            })
            
        # 5. Get total counts
        total_emails = await db.email_logs.count_documents(email_query)
        total_notifications = await db.notifications.count_documents(notif_query)
        
        return {
            "success": True,
            "emails": sanitized_emails,
            "notifications": sanitized_notifs,
            "jobs": [{"id": k, "title": v} for k, v in job_map.items()],
            "total_emails": total_emails,
            "total_notifications": total_notifications,
            "unread_count": unread_count
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch recruiter emails and notifications: {e}")
        return {
            "success": True,
            "emails": [],
            "notifications": [],
            "jobs": [],
            "total_emails": 0,
            "total_notifications": 0,
            "unread_count": 0
        }
