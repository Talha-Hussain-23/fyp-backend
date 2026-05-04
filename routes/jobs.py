"""
Job Management Routes
Refactored job endpoints with improved error handling, async support, and high-performance caching
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId

from schemas import (
    JDCreate, 
    JDUpdate, 
    JDResponse, 
    PaginatedResponse,
    JobStatusUpdate
)
from utils import (
    get_db, 
    get_document_or_404,
    logger,
    ForbiddenError
)
from utils.validators import validate_object_id
from utils.authorization import verify_job_ownership
from core.auth import get_current_user
from services.processing.core import save_jd
from services.automation.auto_invite import auto_send_interview_invitations
from core.logging_service import log_audit_event

router = APIRouter()

@router.get("/{job_id}/candidates")
async def list_job_candidates(
    job_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """List candidates who applied to a specific job (Recruiter only) (Async)"""
    job_obj_id = validate_object_id(job_id, "Job ID")
    await verify_job_ownership(db, job_obj_id, current_user.id)
    
    pipeline = [
        {"$match": {"job_id": job_id}},
        {"$lookup": {
            "from": "resumes",
            "let": {"resume_id_str": {"$toString": "$resume_id"}},
            "pipeline": [
                {"$match": {"$expr": {"$eq": [{"$toString": "$_id"}, "$$resume_id_str"]}}}
            ],
            "as": "resume_data"
        }},
        {"$lookup": {
            "from": "interviews",
            "let": {"resume_id_str": {"$toString": "$resume_id"}},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$and": [
                            {"$eq": [{"$toString": "$resume_id"}, "$$resume_id_str"]},
                            {"$eq": ["$jd_id", job_id]}
                        ]
                    }
                }}
            ],
            "as": "interview_data"
        }},
        {"$addFields": {
            "proctoring_warning_count": {
                "$max": [
                    {"$ifNull": [{"$arrayElemAt": ["$interview_data.proctoring_warning_count", 0]}, 0]},
                    {"$ifNull": [{"$arrayElemAt": ["$interview_data.total_strikes", 0]}, 0]},
                    {"$size": {"$ifNull": [{"$arrayElemAt": ["$interview_data.proctoring_violations", 0]}, []]}}
                ]
            },
            "interview_score_from_interview": {
                "$let": {
                    "vars": {
                        "raw_score": {
                            "$ifNull": [
                                {"$arrayElemAt": ["$interview_data.final_score", 0]},
                                {"$arrayElemAt": ["$interview_data.avg_score", 0]},
                                None
                            ]
                        }
                    },
                    "in": {
                        "$cond": [
                            {"$eq": ["$$raw_score", None]},
                            None,
                            # FIX #4: Guard double-multiply — if score is already on 0-100 scale (> 10), use as-is
                            {"$cond": [
                                {"$gt": ["$$raw_score", 10]},
                                {"$round": ["$$raw_score", 1]},  # Already 0-100
                                {"$round": [{"$multiply": ["$$raw_score", 10]}, 1]}  # Convert from 0-10
                            ]}
                        ]
                    }
                }
            }
        }},
        {"$project": {
            "_id": 0,
            "id": {"$toString": "$_id"},
            "resume_id": {"$toString": "$resume_id"},
            "name": "$candidate_name",
            "email": "$candidate_email",
            "status": {"$ifNull": ["$status", "New"]},
            "applied_at": "$applied_at",
            "ai_match_score": "$ai_match_score",
            "match_score_breakdown": {"$ifNull": ["$match_score_breakdown", {}]},
            "interview_score": {"$ifNull": ["$interview_score", "$interview_score_from_interview"]},
            "interview_id": {
                "$let": {
                    "vars": {"first_interview": {"$arrayElemAt": ["$interview_data", 0]}},
                    "in": {"$toString": "$$first_interview._id"}
                }
            },
            "interview_status": {"$arrayElemAt": ["$interview_data.status", 0]},
            "proctoring_warning_count": "$proctoring_warning_count"
        }}
    ]
    
    candidates = await db.applications.aggregate(pipeline).to_list(length=1000)
    return {"success": True, "candidates": candidates}

@router.post("", response_model=JDResponse)
async def create_job(
    job_data: JDCreate, 
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Create a new job posting (Recruiter only) (Async)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can create jobs")
    
    try:
        result = await save_jd(job_data, current_user, db)
        jd_id = result.get("jd_id")
        
        # Invalidate Cache
        try:
            from core.cache import get_cache_service
            cache = get_cache_service()
            await cache.clear_pattern(f"jobs:recruiter:{current_user.id}")
        except Exception: pass

        job = await db.jds.find_one({"_id": ObjectId(jd_id)})
        if not job:
            raise HTTPException(status_code=404, detail="Job created but not found")
        
        job["id"] = str(job.pop("_id"))
        job["recruiter_id"] = str(job.get("recruiter_id"))
        job["recruiter_name"] = getattr(current_user, "name", "Unknown")
        return job
        
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_model=PaginatedResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """List jobs for current recruiter (Async)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Access denied")
    
    query = {"recruiter_id": current_user.id, "is_deleted": {"$ne": True}}
    if status and status.lower() not in ["all", "any"]:
        query["status"] = status
    if search:
        query["$text"] = {"$search": search}
    
    pipeline = [
        {"$match": query},
        {"$sort": {"created_at": -1}},
        {"$facet": {
            "metadata": [{"$count": "total"}],
            "data": [{"$skip": (page-1)*per_page}, {"$limit": per_page}]
        }}
    ]
    
    result = await db.jds.aggregate(pipeline).to_list(length=1)
    facet_result = result[0] if result else {"metadata": [], "data": []}
    
    total = facet_result["metadata"][0]["total"] if facet_result["metadata"] else 0
    jobs = facet_result["data"]
    
    now = datetime.now(timezone.utc)
    recruiter_ids = list(set(ObjectId(j.get("recruiter_id")) for j in jobs if j.get("recruiter_id")))
    recruiters = await db.users.find({"_id": {"$in": recruiter_ids}}).to_list(length=len(recruiter_ids))
    recruiters_map = {str(r["_id"]): r.get("name", "Unknown") for r in recruiters}

    for job in jobs:
        # Auto-close check
        if job.get("status") == "open" and job.get("apply_deadline"):
            try:
                deadline = datetime.fromisoformat(job["apply_deadline"].replace("Z", "+00:00"))
                if now > deadline:
                    await db.jds.update_one({"_id": job["_id"]}, {"$set": {"status": "closed"}})
                    job["status"] = "closed"
                    try:
                        await auto_send_interview_invitations(str(job["_id"]), db)
                    except Exception: pass
            except Exception: pass
        
        job["id"] = str(job.pop("_id"))
        rid = str(job.get("recruiter_id"))
        job["recruiter_id"] = rid
        job["recruiter_name"] = recruiters_map.get(rid, "Unknown")
    
    return {
        "success": True,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "items": jobs
    }

@router.get("/{job_id}", response_model=JDResponse)
async def get_job(
    job_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get job details (Async with Cache)"""
    job_obj_id = validate_object_id(job_id, "Job ID")
    
    try:
        from core.cache import get_cache_service
        cache = get_cache_service()
        cached_job = await cache.get(f"job:{job_id}")
        if cached_job and cached_job.get("recruiter_id") == current_user.id:
            return cached_job
    except Exception: pass

    job = await db.jds.find_one({"_id": job_obj_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if str(job.get("recruiter_id")) != current_user.id:
        raise ForbiddenError("Access denied")
        
    job["id"] = str(job.pop("_id"))
    job["recruiter_id"] = str(job.get("recruiter_id"))
    
    recruiter = await db.users.find_one({"_id": ObjectId(job["recruiter_id"])})
    job["recruiter_name"] = recruiter.get("name", "Unknown") if recruiter else "Unknown"
    
    try:
        await cache.set(f"job:{job_id}", job, ttl=300)
    except Exception: pass
    
    return job

@router.put("/{job_id}", response_model=JDResponse)
async def update_job(
    job_id: str,
    update_data: JDUpdate,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update job posting (Async)"""
    job_obj_id = validate_object_id(job_id, "Job ID")
    await verify_job_ownership(db, job_obj_id, current_user.id)
    
    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        job = await db.jds.find_one({"_id": job_obj_id})
        job["id"] = str(job["_id"])
        job["recruiter_id"] = str(job.get("recruiter_id"))
        return job
    
    # Handle activation/scheduling
    if update_dict.get("status") == "open" or update_dict.get("start_date") or update_dict.get("apply_deadline"):
        other_updates = {k: v for k, v in update_dict.items() if k not in ["status", "apply_deadline", "start_date"]}
        if other_updates:
            other_updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.jds.update_one({"_id": ObjectId(job_id)}, {"$set": other_updates})

        from services.automation.job_automation import activate_job
        job = await activate_job(job_id, db, current_user, new_deadline=update_dict.get("apply_deadline"), start_date=update_dict.get("start_date"))
        return job

    # Standard update
    update_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.jds.update_one({"_id": ObjectId(job_id)}, {"$set": update_dict})

    # Invalidate Cache
    try:
        from core.cache import get_cache_service
        cache = get_cache_service()
        await cache.delete(f"job:{job_id}")
        await cache.clear_pattern(f"jobs:recruiter:{current_user.id}")
    except Exception: pass

    # Auto-invite logic if closing
    if update_dict.get("status") in ["closed", "filled"]:
        try:
            await auto_send_interview_invitations(job_id, db)
        except Exception: pass
            
    job = await db.jds.find_one({"_id": ObjectId(job_id)})
    job["id"] = str(job.pop("_id"))
    job["recruiter_id"] = str(job.get("recruiter_id"))
    return job

@router.delete("/{job_id}")
async def archive_job(
    job_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Archive job posting (soft delete) (Async)"""
    job_obj_id = validate_object_id(job_id, "Job ID")
    await verify_job_ownership(db, job_obj_id, current_user.id)
    
    await db.jds.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {
            "status": "archived",
            "is_deleted": True,
            "deleted_at": datetime.now(timezone.utc),
            "deleted_by": current_user.id,
            "archived_at": datetime.now(timezone.utc)
        }}
    )
    
    # Invalidate Cache
    try:
        from core.cache import get_cache_service
        cache = get_cache_service()
        await cache.delete(f"job:{job_id}")
        await cache.clear_pattern(f"jobs:recruiter:{current_user.id}")
    except Exception: pass

    return {"success": True, "message": "Job archived successfully"}

@router.post("/{job_id}/reopen")
async def reopen_job(
    job_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Reopen a closed/filled job (Async)"""
    job_obj_id = validate_object_id(job_id, "Job ID")
    await verify_job_ownership(db, job_obj_id, current_user.id)
    
    from services.automation.job_automation import activate_job
    try:
        updated_job = await activate_job(job_id, db, current_user)
        
        # Invalidate Cache
        try:
            from core.cache import get_cache_service
            cache = get_cache_service()
            await cache.delete(f"job:{job_id}")
            await cache.clear_pattern(f"jobs:recruiter:{current_user.id}")
        except Exception: pass

        return updated_job
    except Exception as e:
        logger.error(f"Failed to reopen job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reopen job: {str(e)}")
