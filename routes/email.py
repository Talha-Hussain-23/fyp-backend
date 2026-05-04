"""
Email Routes (Async)
Endpoints for sending and tracking emails
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from bson import ObjectId
from utils import get_db, logger
from core.auth import get_current_user
from services.email.email_logger import get_email_logger
from services.email.email_service import enqueue_templated_email, send_interview_invitation_email

router = APIRouter()

class EmailRequest(BaseModel):
    to_email: str
    candidate_name: str
    template: str = "recruiter_announcement"
    subject: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None

@router.post("/send")
async def send_email(
    request: EmailRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Enqueue an email for delivery (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Only recruiters can send emails")
    
    try:
        variables = request.variables or {}
        subject = request.subject or f"Message from {current_user.name or 'Smart Recruiter AI'}"
        
        # Inject standard variables if missing
        if "recruiterName" not in variables:
            variables["recruiterName"] = current_user.name or current_user.email
        if "candidateName" not in variables:
            variables["candidateName"] = request.candidate_name
        if "subject" not in variables:
            variables["subject"] = subject
        if "customMessage" not in variables and "message" in variables:
            variables["customMessage"] = variables["message"]
            
        task_id = await enqueue_templated_email(
            db=db,
            to_email=request.to_email,
            template_name=request.template,
            variables=variables,
            subject=subject
        )
        
        if task_id:
            return {"success": True, "message": "Email queued for delivery", "task_id": task_id}
        else:
            return {"success": False, "message": "Failed to queue email"}
    except Exception as e:
        logger.error(f"Failed to queue email: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/resend/{interview_id}")
async def resend_interview_email(
    interview_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Resend interview invitation email (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Only recruiters can resend emails")
    
    if not ObjectId.is_valid(interview_id):
        raise HTTPException(status_code=400, detail="Invalid interview ID")

    try:
        # Get interview, resume, and job in parallel
        import asyncio
        interview_task = db.interviews.find_one({"_id": ObjectId(interview_id)})
        recruiter_task = db.users.find_one({"_id": ObjectId(current_user.id)})
        
        interview, recruiter = await asyncio.gather(interview_task, recruiter_task)
        if not interview: raise HTTPException(status_code=404, detail="Interview not found")

        resume = await db.resumes.find_one({"_id": ObjectId(interview["resume_id"])})
        jd = await db.jds.find_one({"_id": ObjectId(interview["jd_id"])})
        
        if not resume or not jd: raise HTTPException(status_code=404, detail="Associated data not found")
        
        recruiter_name = recruiter.get("name", current_user.email) if recruiter else "Smart Recruiter AI Team"
        company_name = recruiter.get("organization", "Smart Recruiter AI") if recruiter else "Smart Recruiter AI"
        
        await send_interview_invitation_email(
            to_email=resume["email"],
            candidate_name=resume.get("candidate_name", "Candidate"),
            job_title=jd.get("title", "Position"),
            interview_id=interview_id,
            interview_token=interview.get("interview_token"),
            recruiter_name=recruiter_name,
            company_name=company_name,
            db=db
        )
        
        # Update email status
        await db.interviews.update_one(
            {"_id": ObjectId(interview_id)},
            {"$set": {
                "email_status.sent": True,
                "email_status.sent_at": datetime.now(timezone.utc).isoformat(),
                "email_status.resent": True
            }}
        )
        
        return {"success": True, "message": "Email resent successfully"}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Failed to resend email: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/status/{jd_id}")
async def get_email_status_for_job(
    jd_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get email delivery status for all candidates in a job (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Only recruiters can view email status")
    
    try:
        interviews = await db.interviews.find({"jd_id": jd_id}).to_list(length=1000)
        status_list = []
        for interview in interviews:
            resume = await db.resumes.find_one({"_id": ObjectId(interview["resume_id"])})
            email_status = interview.get("email_status", {})
            status_list.append({
                "interview_id": str(interview["_id"]),
                "candidate_name": resume.get("candidate_name", "Unknown") if resume else "Unknown",
                "email_sent": email_status.get("sent", False),
                "sent_at": email_status.get("sent_at")
            })
        
        total = len(status_list)
        sent = sum(1 for s in status_list if s["email_sent"])
        return {
            "success": True,
            "statistics": {"total": total, "sent": sent, "failed": total - sent},
            "emails": status_list
        }
    except Exception as e:
        logger.error(f"Failed to get email status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/analytics")
async def get_email_analytics(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get email analytics for recruiter (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Only recruiters can view analytics")
    
    try:
        email_logger = get_email_logger(db)
        interviews = await db.interviews.find({"recruiter_id": current_user.id}).to_list(length=1000)
        interview_ids = [str(i["_id"]) for i in interviews]
        
        # Parallel fetch of logs and history
        import asyncio
        history_task = email_logger.get_email_history(limit=20) # Simplified for dashboard
        failures_task = email_logger.get_failed_emails(limit=10)
        
        history, failures = await asyncio.gather(history_task, failures_task)
        
        # Aggregate stats (Async)
        total = await db.email_audit_log.count_documents({"interview_id": {"$in": interview_ids}})
        successful = await db.email_audit_log.count_documents({"interview_id": {"$in": interview_ids}, "status": "success"})
        
        return {
            "success": True,
            "statistics": {
                "total_emails": total, "successful": successful, "failed": total - successful,
                "success_rate": round((successful / total * 100) if total > 0 else 0, 2)
            },
            "recent_logs": history,
            "failed_emails": failures
        }
    except Exception as e:
        logger.error(f"Failed to get email analytics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
