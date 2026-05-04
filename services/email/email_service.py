"""
Complete Email Integration System (Async)
Templated email service using Gmail API and Durable Queue
"""
import os
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any
from dotenv import load_dotenv
from fastapi import HTTPException
from bson import ObjectId
import logging
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)
load_dotenv()

BASE_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Setup Jinja2 Environment
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
template_dir = os.path.join(backend_dir, "templates", "email")
env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(['html', 'xml'])
)

def render_template(template_name: str, variables: Dict) -> str:
    """Render email template using Jinja2"""
    try:
        template = env.get_template(f"{template_name}.html")
        variables["now"] = datetime.now(timezone.utc)
        variables["base_url"] = BASE_URL
        return template.render(**variables)
    except Exception as e:
        logger.error(f"Error rendering template {template_name}: {e}")
        raise

async def log_email(
    db, to: str, subject: str, template: str, variables: Dict, status: str, 
    error_message: Optional[str] = None
) -> Optional[str]:
    """Log email send attempt to MongoDB (Async)"""
    if db is None: return None
    try:
        log_doc = {
            "to": to, "subject": subject, "template": template, "variables": variables,
            "status": status, "errorMessage": error_message,
            "sentAt": datetime.now(timezone.utc).isoformat(),
            "provider": "Gmail API", "created_at": datetime.now(timezone.utc).isoformat()
        }
        result = await db.email_logs.insert_one(log_doc)
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Failed to log email: {e}")
        return None

async def send_email_via_gmail_api(
    to_email: str, subject: str, html_content: str, reply_to: Optional[str] = None, db = None
) -> Dict:
    """Send email using Gmail API (Async Wrapper)"""
    try:
        from .gmail_utils import send_email_via_gmail
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: send_email_via_gmail(
            to_email=to_email, subject=subject, html_content=html_content, reply_to=reply_to
        ))
        
        log_id = await log_email(db, to_email, subject, "raw", {}, "sent") if db is not None else None
        return {"success": True, "recipient": to_email, "log_id": log_id}
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        if db is not None: await log_email(db, to_email, subject, "raw", {}, "failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

async def _enqueue_email(
    db, to_email: str, template_name: str, template_data: Dict, 
    subject: Optional[str] = None, priority: int = 5, is_async: bool = True
) -> Optional[str]:
    """Enqueue email task for the EmailWorker (Shared Async/Sync)"""
    if db is None: return None
    task_id = str(ObjectId())
    task_doc = {
        "task_id": task_id, "to_email": to_email, "template_name": template_name,
        "template_data": template_data, "subject": subject, "status": "PENDING",
        "priority": priority, "attempts": 0, "max_attempts": 5,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        if is_async:
            await db.email_queue.insert_one(task_doc)
        else:
            db.email_queue.insert_one(task_doc)
        return task_id
    except Exception as e:
        logger.error(f"Failed to enqueue email (async={is_async}): {e}")
        return None

def _enqueue_email_sync(
    db, to_email: str, template_name: str, template_data: Dict, 
    subject: Optional[str] = None, priority: int = 5
) -> Optional[str]:
    """Internal sync helper for email queueing"""
    # Simply call the logic with is_async=False
    # Since _enqueue_email is a coroutine, we can't call it directly from sync
    # We'll just duplicate the small logic or refactor it.
    # Refactoring now:
    if db is None: return None
    task_id = str(ObjectId())
    task_doc = {
        "task_id": task_id, "to_email": to_email, "template_name": template_name,
        "template_data": template_data, "subject": subject, "status": "PENDING",
        "priority": priority, "attempts": 0, "max_attempts": 5,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        db.email_queue.insert_one(task_doc)
        return task_id
    except Exception as e:
        logger.error(f"Failed to enqueue email (sync): {e}")
        return None

async def enqueue_templated_email(db, to_email: str, template_name: str, variables: Dict, subject: Optional[str] = None) -> Optional[str]:
    return await _enqueue_email(db, to_email, template_name, variables, subject)

async def send_interview_invitation_email(
    to_email: str, candidate_name: str, job_title: str, interview_id: str, 
    interview_token: Optional[str] = None, recruiter_name: Optional[str] = None, 
    company_name: Optional[str] = None, db = None
) -> Optional[str]:
    """Queue interview invitation email (Async)"""
    url = f"{BASE_URL}/interview?interview_id={interview_id}"
    if interview_token: url += f"&token={interview_token}"
    
    # Reclaim link — path MUST be /interview-reclaim (the actual frontend route in App.js).
    # Must also include interview_id and token so InterviewReclaim.js can auto-identify the session.
    reclaim_url = f"{BASE_URL}/interview-reclaim?interview_id={interview_id}"
    if interview_token:
        reclaim_url += f"&token={interview_token}"
    
    return await _enqueue_email(db, to_email, "interview_invite", {
        "candidateName": candidate_name, 
        "jobTitle": job_title, 
        "link": url,
        "reclaimLink": reclaim_url,
        "recruiterName": recruiter_name or "Smart Recruiter Team",
        "companyName": company_name or "Smart Recruiter AI"
    })

async def send_password_reset_email(to_email: str, user_name: str, reset_token: str, db) -> Optional[str]:
    url = f"{BASE_URL}/reset-password/{reset_token}"
    return await _enqueue_email(db, to_email, "password_reset", {"userName": user_name, "resetLink": url})

async def send_email_verification_email(to_email: str, user_name: str, verification_token: str, db) -> Optional[str]:
    url = f"{BASE_URL}/verify-email/{verification_token}"
    return await _enqueue_email(db, to_email, "email_verification", {"userName": user_name, "verificationLink": url})

async def send_templated_email(
    to_email: str, template_name: str, variables: Dict, subject: Optional[str] = None, db = None
) -> Dict:
    """Render and SEND email immediately (Async)"""
    html = render_template(template_name, variables)
    if not subject:
        subject = f"Notification from Smart Recruiter AI - {template_name.replace('_', ' ').title()}"
    
    return await send_email_via_gmail_api(
        to_email=to_email, subject=subject, html_content=html, 
        reply_to=variables.get("recruiterEmail"), db=db
    )

# Legacy Aliases for compatibility
send_templated_email_immediate = send_templated_email
enqueue_email = enqueue_templated_email

# Automated Aliases for template wrappers
async def send_password_changed_email(db, to_email: str, user_name: str):
    return await enqueue_templated_email(db, to_email, "password_changed", {
        "userName": user_name,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    })

async def send_application_submitted_email(db, to_email: str, candidate_name: str, job_title: str, recruiter_name: str = "Smart Recruiter Team"):
    return await enqueue_templated_email(db, to_email, "application_submitted", {
        "candidateName": candidate_name, 
        "jobTitle": job_title,
        "recruiterName": recruiter_name
    })

async def send_cheating_warning_email(db, to_email: str, candidate_name: str, reason: str, warning_count: int = 1, recruiter_name: str = "Proctoring System"):
    """Async cheating warning"""
    return await _enqueue_email(db, to_email, "cheating_warning", {
        "candidateName": candidate_name, 
        "reason": reason,
        "warningCount": warning_count,
        "recruiterName": recruiter_name
    })

def send_cheating_warning_email_sync(db, to_email: str, candidate_name: str, reason: str, warning_count: int = 1, recruiter_name: str = "Proctoring System"):
    """Sync cheating warning for proctoring server"""
    return _enqueue_email_sync(db, to_email, "cheating_warning", {
        "candidateName": candidate_name, 
        "reason": reason,
        "warningCount": warning_count,
        "recruiterName": recruiter_name
    })

async def send_cheating_disqualification_email(db, to_email: str, candidate_name: str, reason: str = "Multiple violations", recruiter_name: str = "Proctoring System"):
    """Async disqualification"""
    return await _enqueue_email(db, to_email, "cheating_disqualification", {
        "candidateName": candidate_name,
        "reason": reason,
        "recruiterName": recruiter_name
    })

def send_cheating_disqualification_email_sync(db, to_email: str, candidate_name: str, reason: str = "Multiple violations", recruiter_name: str = "Proctoring System"):
    """Sync disqualification for proctoring server"""
    return _enqueue_email_sync(db, to_email, "cheating_disqualification", {
        "candidateName": candidate_name,
        "reason": reason,
        "recruiterName": recruiter_name
    })

async def send_result_selected_email(
    db, to_email: str, candidate_name: str, job_title: str, 
    score: Optional[float] = None, recruiter_name: str = "Smart Recruiter Team",
    custom_message: str = "We are impressed by your qualifications and look forward to your journey with us."
):
    """Queue selection email with optional score (Async)"""
    score_section = f'<div class="card" style="border-left: 4px solid #10b981; background-color: #f0fdf4; padding: 15px; border-radius: 8px; margin: 20px 0;"><h3 style="margin: 0; color: #065f46; font-size: 16px;">Performance Overview</h3><p style="margin: 5px 0 0 0; font-size: 24px; font-weight: bold; color: #047857;">{score}/100</p><p style="margin: 0; font-size: 14px; color: #059669;">Matching Score</p></div>' if score is not None else ""
    
    return await enqueue_templated_email(db, to_email, "result_selected", {
        "candidateName": candidate_name, 
        "jobTitle": job_title,
        "score": score,
        "scoreSection": score_section,
        "recruiterName": recruiter_name,
        "customMessage": custom_message
    })

async def send_result_rejected_email(
    db, to_email: str, candidate_name: str, job_title: str, 
    score: Optional[float] = None, recruiter_name: str = "Smart Recruiter Team",
    feedback: str = "While we found your background interesting, we have decided to move forward with other candidates at this time."
):
    """Queue rejection email with optional score (Async)"""
    score_section = f'<div class="card" style="border-left: 4px solid #94a3b8; background-color: #f8fafc; padding: 15px; border-radius: 8px; margin: 20px 0;"><h3 style="margin: 0; color: #475569; font-size: 16px;">Performance Overview</h3><p style="margin: 5px 0 0 0; font-size: 24px; font-weight: bold; color: #1e293b;">{score}/100</p><p style="margin: 0; font-size: 14px; color: #64748b;">Matching Score</p></div>' if score is not None else ""
    
    return await enqueue_templated_email(db, to_email, "result_rejected", {
        "candidateName": candidate_name, 
        "jobTitle": job_title,
        "score": score,
        "scoreSection": score_section,
        "recruiterName": recruiter_name,
        "customMessage": feedback
    })

async def send_reclaim_approved_email(
    db, to_email: str, candidate_name: str, job_title: str = "Position", 
    interview_id: str = "", interview_token: str = "", 
    recruiter_name: str = "Recruiter", company_name: str = "Smart Hiring"
):
    """Queue reclaim approval email (Async)"""
    url = f"{BASE_URL}/interview?interview_id={interview_id}"
    if interview_token: url += f"&token={interview_token}"
    
    return await enqueue_templated_email(db, to_email, "reclaim_approved", {
        "candidateName": candidate_name,
        "jobTitle": job_title,
        "interviewId": interview_id,
        "interviewToken": interview_token,
        "link": url,
        "recruiterName": recruiter_name,
        "companyName": company_name
    })

async def send_reclaim_rejected_email(
    db, to_email: str, candidate_name: str, job_title: str = "Position",
    rejection_message: str = "", recruiter_name: str = "Recruiter", 
    company_name: str = "Smart Hiring"
):
    """Queue reclaim rejection email (Async)"""
    return await enqueue_templated_email(db, to_email, "reclaim_rejected", {
        "candidateName": candidate_name,
        "jobTitle": job_title,
        "rejectionMessage": rejection_message,
        "recruiterName": recruiter_name,
        "companyName": company_name
    })

async def send_status_update_email(
    db, to_email: str, candidate_name: str, status: str, 
    job_title: str = "Position", feedback: Optional[str] = None, 
    recruiter_name: str = "Smart Recruiter Team"
):
    """Queue general status update email (Async)"""
    return await enqueue_templated_email(db, to_email, "status_update", {
        "candidateName": candidate_name, 
        "jobTitle": job_title,
        "friendlyStatus": status,
        "newStatus": status,
        "feedback": feedback,
        "recruiterName": recruiter_name
    })
