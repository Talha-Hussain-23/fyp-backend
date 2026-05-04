"""
Automated Job Workflow System
Handles automatic status updates, interview email sending, and deadline management
"""

import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
from bson import ObjectId
from pymongo.database import Database
from services.email.email_service import send_interview_invitation_email
from core.logging_service import log_audit_event
import logging

# logging.basicConfig(level=logging.INFO)  # Removed to avoid conflict with app config
logger = logging.getLogger(__name__)


async def check_and_process_deadlines(db: Database) -> Dict:
    """
    Check all jobs with deadlines and process them asynchronously:
    1. Update job status to 'closed' if deadline passed
    2. Send interview emails to all applicants
    3. Create interviews for applicants who don't have one yet
    
    Returns summary of processed jobs
    """
    try:
        now = datetime.now(timezone.utc)
        from utils.timezone_utils import format_local_time
        now_local_str = format_local_time(now)
        
        logger.info(f"⏰ [UTC+5] Deadline check started at {now_local_str}")
        
        processed_jobs = []
        errors = []
        
        # Find all jobs with deadlines that are still open
        cursor = db.jds.find({
            "apply_deadline": {"$exists": True, "$ne": None},
            "$or": [
                {"status": {"$in": ["open", None]}},
                {"status": {"$exists": False}}
            ],
            "deadline_processed": {"$ne": True}
        })
        
        async for job in cursor:
            try:
                job_id = str(job["_id"])
                deadline_str = job.get("apply_deadline")
                
                if not deadline_str:
                    continue
                
                # Parse deadline
                deadline = None
                try:
                    from utils.timezone_utils import parse_deadline_from_utc
                    deadline = parse_deadline_from_utc(deadline_str)
                    
                    if deadline and deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=timezone.utc)
                    
                    if not deadline:
                        # Fallback
                        if 'Z' in deadline_str or '+' in deadline_str or deadline_str.count('-') >= 3:
                            deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                        else:
                            deadline = datetime.fromisoformat(deadline_str)
                            deadline = deadline.replace(tzinfo=timezone.utc)
                except Exception:
                    try:
                        from dateutil import parser
                        deadline = parser.parse(deadline_str)
                        if deadline.tzinfo is None:
                            deadline = deadline.replace(tzinfo=timezone.utc)
                    except:
                        logger.warning(f"Could not parse deadline for job {job_id}: {deadline_str}")
                        continue
                
                if not deadline:
                    continue
                
                if now >= deadline:
                    logger.info(f"⏰ [UTC+5] Deadline passed for job {job_id} ({job.get('title', 'Untitled')}) → status changing to 'closed'")
                    
                    now_iso = now.isoformat()
                    update_filter = {
                        "_id": ObjectId(job_id),
                        "deadline_processed": {"$ne": True}
                    }
                    
                    update_result = await db.jds.update_one(
                        update_filter,
                        {
                            "$set": {
                                "status": "closed",
                                "status_updated_at": now_iso,
                                "deadline_processed": True,
                                "deadline_processed_at": now_iso,
                                "updated_at": now_iso
                            }
                        }
                    )
                    
                    if update_result.modified_count > 0:
                        logger.info(f"✅ [UTC+5] Updated job {job_id} status to 'closed'")
                        
                        # Audit Log
                        await log_audit_event(
                            db=db,
                            user_id="system_auto_close",
                            action="auto_close_job",
                            entity_type="job",
                            entity_id=job_id,
                            details={"reason": "deadline_passed", "closed_at": now_iso}
                        )

                        # Use auto_invite to send invitations (Async)
                        try:
                            from services.automation.auto_invite import auto_send_interview_invitations
                            invite_result = await auto_send_interview_invitations(job_id, db)
                            
                            if invite_result.get("success"):
                                processed_jobs.append({
                                    "job_id": job_id,
                                    "job_title": job.get("title", "Untitled"),
                                    "emails_sent": invite_result.get("invited", 0)
                                })
                        except Exception as e:
                            logger.error(f"Error sending invitations for job {job_id}: {e}")
                            errors.append(f"Job {job_id}: {str(e)}")
            
            except Exception as e:
                logger.error(f"Error processing job {job.get('_id')}: {e}")
                errors.append(str(e))
        
        return {
            "success": True,
            "processed_jobs": processed_jobs,
            "total": len(processed_jobs),
            "errors": errors
        }
    
    except Exception as e:
        logger.error(f"Error in check_and_process_deadlines: {e}")
        return {"success": False, "error": str(e)}


async def send_evaluation_emails_on_status_update(
    application_id: str,
    new_status: str,
    db: Database,
    current_user: Any = None,
    send_email: bool = True
) -> Dict:
    """Send evaluation emails when recruiter updates application status (Async)"""
    if not send_email:
        return {"success": True, "email_sent": False, "reason": "send_email flag is False"}
        
    try:
        application = await db.applications.find_one({"_id": ObjectId(application_id)})
        if not application:
            return {"success": False, "error": "Application not found"}
        
        job = await db.jds.find_one({"_id": ObjectId(application["job_id"])})
        if not job:
            return {"success": False, "error": "Job not found"}
        
        candidate_email = application.get("candidate_email")
        candidate_name = application.get("candidate_name", "Candidate")
        job_title = job.get("title", "Position")
        
        if not candidate_email:
            return {"success": False, "error": "No candidate email found"}
        
        # Get interview score/details
        resume_id = application.get("resume_id")
        score = None
        if resume_id:
            interview = await db.interviews.find_one({
                "resume_id": resume_id,
                "jd_id": application["job_id"]
            })
            if interview and interview.get("avg_score"):
                score = interview.get("avg_score") * 10
        
        # Get Recruiter Details
        recruiter_name = "Recruitment Team"
        company_name = "Smart Recruiter AI"
        
        if current_user:
            recruiter_name = getattr(current_user, "name", current_user.email)
            company_name = getattr(current_user, "organization", "Smart Recruiter AI")
        else:
            recruiter = await db.users.find_one({"_id": ObjectId(job.get("recruiter_id"))})
            if recruiter:
                recruiter_name = recruiter.get("name", recruiter.get("email", "Recruitment Team"))
                company_name = recruiter.get("organization", "Smart Recruiter AI")

        # Send appropriate email
        from services.email.email_service import (
            send_result_selected_email, 
            send_result_rejected_email,
            send_interview_invitation_email
        )
        
        if new_status == "Hired":
            await send_result_selected_email(
                to_email=candidate_email, 
                candidate_name=candidate_name, 
                job_title=job_title, 
                score=score, 
                recruiter_name=recruiter_name,
                db=db
            )
            return {"success": True, "type": "acceptance"}
        elif new_status == "Rejected":
            await send_result_rejected_email(
                to_email=candidate_email, 
                candidate_name=candidate_name, 
                job_title=job_title, 
                score=score, 
                recruiter_name=recruiter_name,
                db=db
            )
            return {"success": True, "type": "rejection"}
        elif new_status == "Interview":
            # 1. Ensure interview exists
            interview = await db.interviews.find_one({
                "jd_id": str(job["_id"]),
                "resume_id": str(resume_id)
            })
            
            interview_id = None
            interview_token = None
            
            if not interview:
                from services.interview.sectioned_interview import create_sectioned_interview
                interview_id = await create_sectioned_interview(str(job["_id"]), str(resume_id), db)
                interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
                interview_token = interview.get("interview_token")
            else:
                interview_id = str(interview["_id"])
                interview_token = interview.get("interview_token")
                
            # 2. Send Invitation (using pre-fetched recruiter_name and company_name)
            await send_interview_invitation_email(
                to_email=candidate_email,
                candidate_name=candidate_name,
                job_title=job_title,
                interview_id=interview_id,
                interview_token=interview_token,
                recruiter_name=recruiter_name,
                company_name=company_name,
                db=db
            )
            
            # Sync interview ID back to application
            await db.applications.update_one(
                {"_id": ObjectId(application_id)},
                {"$set": {"interview_id": interview_id}}
            )
            
            return {"success": True, "type": "interview_invitation", "interview_id": interview_id}
            
        return {"success": True, "email_sent": False, "status_ignored": new_status}
    except Exception as e:
        logger.error(f"Error in send_evaluation_emails_on_status_update: {e}")
        return {"success": False, "error": str(e)}



async def activate_job(job_id: str, db: Database, user, new_deadline: Optional[str] = None, start_date: Optional[str] = None) -> Dict:
    """Activates a job or schedules it for future activation (Async)."""
    job = await db.jds.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise ValueError("Job not found")
        
    if str(job.get("recruiter_id")) != user.id:
        raise PermissionError("Access denied")

    now = datetime.now(timezone.utc)
    final_deadline = None
    final_start_date = None
    new_status = "open"
    
    def parse_date(d_str):
        if not d_str: return None
        try:
            d = datetime.fromisoformat(d_str.replace("Z", "+00:00"))
            return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        except Exception: return None

    if start_date:
        parsed_start = parse_date(start_date)
        if parsed_start:
            final_start_date = start_date
            if parsed_start > now: new_status = "scheduled"

    if new_deadline:
        parsed_new = parse_date(new_deadline)
        if parsed_new and parsed_new > now:
            final_deadline = new_deadline

    if not final_deadline:
        existing_deadline_str = job.get("apply_deadline")
        parsed_existing = parse_date(existing_deadline_str)
        if parsed_existing and parsed_existing > now:
            final_deadline = existing_deadline_str
        elif new_status == "open":
            final_deadline = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"
    
    update_data = {
        "status": new_status,
        "apply_deadline": final_deadline,
        "start_date": final_start_date or job.get("start_date"),
        "closed_at": None,
        "closed_reason": None,
        "archived": False,
        "status_updated_at": now.isoformat(),
        "deadline_processed": False,
        "updated_at": now.isoformat()
    }
    
    await db.jds.update_one({"_id": ObjectId(job_id)}, {"$set": update_data})
    
    # Audit trail
    await log_audit_event(db=db, user_id=user.id, action="update_job_status", entity_type="job", entity_id=job_id, details={"new_status": new_status})
    
    # Invalidate Cache
    try:
        from core.cache import get_cache_service
        cache = get_cache_service()
        await cache.delete(f"job:{job_id}")
        await cache.clear_pattern(f"jobs:recruiter:{user.id}")
    except: pass

    updated_job = await db.jds.find_one({"_id": ObjectId(job_id)})
    if updated_job:
        updated_job["id"] = str(updated_job.pop("_id"))
        updated_job["recruiter_id"] = str(updated_job.get("recruiter_id"))
        updated_job["recruiter_name"] = getattr(user, "name", "Unknown")
        
    return updated_job

async def process_scheduled_jobs(db: Database):
    """Checks for jobs with status='scheduled' and start_date <= NOW. (Async)"""
    now = datetime.now(timezone.utc)
    cursor = db.jds.find({"status": "scheduled"})
    
    async for job in cursor:
        start_date_str = job.get("start_date")
        if not start_date_str: continue
             
        try:
            start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            if start_date.tzinfo is None: start_date = start_date.replace(tzinfo=timezone.utc)
            
            if now >= start_date:
                await db.jds.update_one(
                    {"_id": job["_id"]},
                    {"$set": {"status": "open", "status_updated_at": now.isoformat()}}
                )
                logger.info(f"Scheduled Job {job['_id']} automatically opened.")
        except Exception as e:
            logger.error(f"Error processing scheduled job {job['_id']}: {e}")


