"""
Screening Routes (Async)
Endpoints for candidate screening details and actions
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from bson import ObjectId
from datetime import datetime
from utils import (
    get_db, 
    logger,
    ForbiddenError,
    NotFoundError
)
from core.auth import get_current_user

router = APIRouter()

@router.get("/{screening_id}/detail")
async def get_screening_detail(
    screening_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get detailed screening information for a candidate (Async)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can view screening details")
    
    if not ObjectId.is_valid(screening_id):
        raise NotFoundError("Invalid screening ID format")

    # Get screening record from screenings or applications fallback
    screening = await db.candidate_screenings.find_one({"_id": ObjectId(screening_id)})
    if not screening:
        screening = await db.applications.find_one({"_id": ObjectId(screening_id)})
    
    if not screening:
        raise NotFoundError("Screening record not found")
    
    # Get resume data if available
    resume = None
    resume_id = screening.get("resume_id")
    if resume_id and ObjectId.is_valid(str(resume_id)):
        resume = await db.resumes.find_one({"_id": ObjectId(str(resume_id))})

    # Helper to serialize ObjectId
    def serialize_mongo(obj):
        if isinstance(obj, ObjectId): return str(obj)
        if isinstance(obj, list): return [serialize_mongo(item) for item in obj]
        if isinstance(obj, dict): return {k: serialize_mongo(v) for k, v in obj.items()}
        return obj

    return {
        "success": True,
        "screening": serialize_mongo(screening),
        "resume": serialize_mongo(resume) if resume else None
    }

@router.post("/{screening_id}/action")
async def take_screening_action(
    screening_id: str,
    body: dict = Body(...),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Take action on a screening (shortlist, reject, etc.) (Async)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can take screening actions")
    
    action = body.get("action", "").lower()
    if action not in ["shortlisted", "rejected", "review", "interview"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    if not ObjectId.is_valid(screening_id):
        raise HTTPException(status_code=400, detail="Invalid screening ID format")

    update_doc = {
        "$set": {
            "status": action if action != "interview" else action.title(),
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by": current_user.id
        }
    }

    # Try to update in screenings collection first
    result = await db.candidate_screenings.update_one({"_id": ObjectId(screening_id)}, update_doc)
    
    if result.matched_count == 0:
        # Fallback to applications collection
        await db.applications.update_one({"_id": ObjectId(screening_id)}, update_doc)
    
    logger.info(f"Screening {screening_id} updated to {action} by {current_user.email}")
    return {"success": True, "message": f"Status updated to {action}"}
