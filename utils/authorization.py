"""
Authorization Helpers
Prevents IDOR (Insecure Direct Object Reference) attacks
"""
from fastapi import HTTPException
from bson import ObjectId
from typing import Optional


async def verify_job_ownership(db, job_id: ObjectId, recruiter_id: str):
    """Verify recruiter owns the job (Async)"""
    job = await db.jds.find_one({
        "_id": job_id,
        "recruiter_id": recruiter_id
    })
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or access denied")
    
    return job


async def verify_interview_access(db, interview_id: ObjectId, user_id: str, is_recruiter: bool):
    """Verify user has access to interview, handling missing recruiter_id by checking job ownership (Async)"""
    interview = await db.interviews.find_one({"_id": interview_id})
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
        
    if is_recruiter:
        recruiter_id = interview.get("recruiter_id")
        # Ensure recruiter_id is checked as string if present
        if recruiter_id and str(recruiter_id) == user_id:
            pass
        else:
            jd_id = interview.get("jd_id")
            if jd_id:
                try:
                    job = await db.jds.find_one({"_id": ObjectId(str(jd_id)), "recruiter_id": user_id})
                    if not job:
                        raise HTTPException(status_code=403, detail="Access denied: Recruiter does not own the associated job")
                except Exception:
                    raise HTTPException(status_code=403, detail="Access denied: Invalid job reference")
            else:
                raise HTTPException(status_code=403, detail="Access denied to this interview")
    else:
        candidate_id = interview.get("candidate_id")
        if not candidate_id or str(candidate_id) != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
            
    return interview


async def verify_application_access(db, application_id: ObjectId, user_id: str, is_recruiter: bool):
    """Verify user has access to application (Async)"""
    application = await db.applications.find_one({"_id": application_id})
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    
    if is_recruiter:
        job = await db.jds.find_one({"_id": ObjectId(application["job_id"]), "recruiter_id": user_id})
        if not job: raise HTTPException(status_code=403, detail="Access denied")
    else:
        if application.get("candidate_email") != user_id and application.get("candidate_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    return application


async def verify_reclaim_request_access(db, reclaim_id: ObjectId, user_id: str, is_recruiter: bool):
    """Verify user has access to reclaim request (Async)"""
    reclaim = await db.reclaim_requests.find_one({"_id": reclaim_id})
    if not reclaim:
        raise HTTPException(status_code=404, detail="Reclaim request not found")
    
    if is_recruiter:
        job = await db.jds.find_one({"_id": ObjectId(reclaim.get("job_id")), "recruiter_id": user_id})
        if not job: raise HTTPException(status_code=403, detail="Access denied")
    else:
        interview = await db.interviews.find_one({"_id": ObjectId(reclaim.get("interview_id")), "candidate_id": user_id})
        if not interview: raise HTTPException(status_code=403, detail="Access denied")
    
    return reclaim


async def verify_resume_access(db, resume_id: ObjectId, user_id: str, is_recruiter: bool):
    """Verify user has access to resume (Async)"""
    resume = await db.resumes.find_one({"_id": resume_id})
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    if not is_recruiter:
        if resume.get("uploaded_by") != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    return resume


# ============================================================================
# ROLE-BASED ACCESS CONTROL GUARDS
# ============================================================================

from fastapi import Depends
from core.auth import get_current_user
from utils import logger


def require_recruiter(current_user = Depends(get_current_user)):
    """
    Dependency to ensure current user is a recruiter with an active account.
    
    Use this guard on endpoints that should only be accessible to recruiters,
    such as job creation, application viewing, and candidate management.
    
    Args:
        current_user: Authenticated user from JWT token
        
    Returns:
        User object if authorized
        
    Raises:
        HTTPException: 403 if user is not a recruiter or account is inactive
        
    Example:
        @router.post("/jobs")
        async def create_job(
            job: JobCreate,
            current_user = Depends(require_recruiter),
            db = Depends(get_db)
        ):
            # Only recruiters can access this endpoint
            pass
    """
    # Check if account is active
    if not getattr(current_user, 'is_active', True):
        logger.warning(
            f"🚫 Inactive account access attempt | "
            f"User: {current_user.email} | "
            f"Endpoint: recruiter-only"
        )
        raise HTTPException(
            status_code=403,
            detail="Account has been deactivated. Please contact support."
        )
    
    # Check recruiter role
    if not current_user.is_recruiter:
        logger.warning(
            f"🚫 Unauthorized recruiter access attempt | "
            f"User: {current_user.email} | "
            f"Role: {getattr(current_user, 'role', 'candidate')}"
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied. Recruiter privileges required."
        )
    
    return current_user


def require_active_user(current_user = Depends(get_current_user)):
    """
    Dependency to ensure current user account is active.
    
    Use this guard on endpoints that require an active account,
    regardless of role (recruiter or candidate).
    
    Args:
        current_user: Authenticated user from JWT token
        
    Returns:
        User object if authorized
        
    Raises:
        HTTPException: 403 if account is deactivated
    """
    if not getattr(current_user, 'is_active', True):
        logger.warning(
            f"🚫 Inactive account access | "
            f"User: {current_user.email}"
        )
        raise HTTPException(
            status_code=403,
            detail="Account has been deactivated. Please contact support."
        )
    
    return current_user


def require_candidate(current_user = Depends(get_current_user)):
    """
    Dependency to ensure current user is a candidate with an active account.
    
    Use this guard on endpoints that should only be accessible to candidates,
    such as job applications and interview participation.
    
    Args:
        current_user: Authenticated user from JWT token
        
    Returns:
        User object if authorized
        
    Raises:
        HTTPException: 403 if user is a recruiter or account is inactive
    """
    # Check if account is active
    if not getattr(current_user, 'is_active', True):
        raise HTTPException(
            status_code=403,
            detail="Account has been deactivated. Please contact support."
        )
    
    # Check candidate role
    if current_user.is_recruiter:
        logger.warning(
            f"🚫 Unauthorized candidate access attempt | "
            f"User: {current_user.email} | "
            f"Role: recruiter"
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied. This endpoint is for candidates only."
        )
    
    return current_user


__all__ = [
    'verify_job_ownership',
    'verify_interview_access',
    'verify_application_access',
    'verify_reclaim_request_access',
    'verify_resume_access',
    'require_recruiter',
    'require_active_user',
    'require_candidate'
]
