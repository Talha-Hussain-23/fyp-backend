"""
Application Management Routes
Endpoints for updating application status and listing applications
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from bson import ObjectId
from datetime import datetime

from schemas.candidates import ApplicationStatusUpdate
from utils import (
    get_db, 
    get_document_or_404,
    logger,
    ForbiddenError
)
from utils.validators import validate_object_id  # ✅ Security
from utils.authorization import verify_application_access  # ✅ Security
from core.auth import get_current_user

router = APIRouter()

@router.put("/{application_id}/status")
async def update_application_status(
    application_id: str,
    update_data: ApplicationStatusUpdate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update candidate application status (Optimized with BackgroundTasks)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can update application status")
    
    # ✅ SECURITY FIX: Validate ObjectId and verify access
    app_obj_id = validate_object_id(application_id, "Application ID")
    application = await verify_application_access(db, app_obj_id, current_user.id, is_recruiter=True)
    
    # Check if the job belongs to this recruiter
    from utils import get_document_or_404_async
    job = await get_document_or_404_async(db.jds, application.get("job_id"))
    if str(job.get("recruiter_id")) != current_user.id:
        raise ForbiddenError("You do not have permission to update applications for this job")
    
    
    # Delegate to TransactionService for safety
    from services.infrastructure.transaction_service import TransactionService
    return await TransactionService.update_application_status_safe(
        application_id=application_id,
        update_data=update_data,
        current_user=current_user,
        db=db,
        background_tasks=background_tasks
    )

@router.get("/{application_id}/analytics")
async def get_application_analytics(
    application_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get detailed analytics for a candidate application (Recruiter only)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can access analytics")
    
    # ✅ SECURITY FIX: Validate ObjectId and verify access
    app_obj_id = validate_object_id(application_id, "Application ID")
    application = await verify_application_access(db, app_obj_id, current_user.id, is_recruiter=True)
    
    # Check permissions
    from utils import get_document_or_404_async
    job = await get_document_or_404_async(db.jds, application.get("job_id"))
    if str(job.get("recruiter_id")) != current_user.id:
        raise ForbiddenError("You do not have permission to view analytics for this application")
    
    # Get Interview ID
    interview = await db.interviews.find_one({
        "resume_id": str(application["resume_id"]), 
        "jd_id": str(application["job_id"])
    })
    
    if not interview:
        return {"error": "No interview found for this application"}
    
    from services.analytics.analytics import generate_candidate_profile
    analytics_data = await generate_candidate_profile(str(interview["_id"]), db)
    
    return {
        "success": True,
        "application_id": application_id,
        "candidate_name": application.get("candidate_name"),
        "analytics": analytics_data
    }

@router.get("/test")
async def test_endpoint():
    return {"status": "applications router working"}

@router.get("/")
async def list_all_applications(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """List all candidates across all jobs for the current recruiter"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can access this endpoint")
    
    # 1. Get all job IDs for this recruiter
    # We only need the IDs to filter applications
    recruiter_jobs = await db.jds.find({"recruiter_id": current_user.id}, {"_id": 1, "title": 1}).to_list(length=1000)
    job_ids = [str(job["_id"]) for job in recruiter_jobs]
    job_oids = [job["_id"] for job in recruiter_jobs] # Also keep ObjectIds
    
    job_map = {str(job["_id"]): job.get("title", "Untitled") for job in recruiter_jobs} # Map for easy title lookup
    
    if not job_ids:
        return {"success": True, "candidates": []}

    # 2. Aggregation pipeline to fetch applications and join data
    # Adapted from jobs.py list_job_candidates
    pipeline = [
        # Match applications for any of the recruiter's jobs (String OR ObjectId)
        {"$match": {
            "$or": [
                {"job_id": {"$in": job_ids}},
                {"job_id": {"$in": job_oids}}
            ]
        }},
        
        # Lookup resume data
        {"$lookup": {
            "from": "resumes",
            "let": {"resume_id_str": {"$toString": "$resume_id"}},
            "pipeline": [
                {"$match": {
                    "$expr": {"$eq": [{"$toString": "$_id"}, "$$resume_id_str"]}
                }}
            ],
            "as": "resume_data"
        }},
        
        # Lookup interview data
        {"$lookup": {
            "from": "interviews",
            "let": {
                "resume_id_str": {"$toString": "$resume_id"},
                "job_id_val": "$job_id"
             },
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$and": [
                            {"$eq": [{"$toString": "$resume_id"}, "$$resume_id_str"]},
                            {"$eq": [{"$toString": "$jd_id"}, {"$toString": "$$job_id_val"}]}
                        ]
                    }
                }}
            ],
            "as": "interview_data"
        }},
        
        # Add computed fields
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
                            # FIX #4: Guard double-multiply — if score > 10 it's already on 0-100 scale
                            {"$cond": [
                                {"$gt": ["$$raw_score", 10]},
                                {"$round": ["$$raw_score", 1]},
                                {"$round": [{"$multiply": ["$$raw_score", 10]}, 1]}
                            ]}
                        ]
                    }
                }
            },
            "interview_status": {
                 "$ifNull": [
                    {"$arrayElemAt": ["$interview_data.status", 0]},
                    None
                ]
            }
        }},
        
        # Project final shape
        {"$project": {
            "application_id": {"$toString": "$_id"},
            "id": {"$toString": "$_id"},
            "resume_id": {"$toString": "$resume_id"},
            "job_id": "$job_id", 
            "name": "$candidate_name",
            "email": "$candidate_email",
            "status": {"$ifNull": ["$status", "New"]},
            "applied_at": "$applied_at",
            "ai_match_score": "$ai_match_score",
            "match_score_breakdown": {"$ifNull": ["$match_score_breakdown", {}]},
            "interview_score": {
                "$ifNull": ["$interview_score", "$interview_score_from_interview"]
            },
            "interview_status": "$interview_status",
            "interview_id": {"$toString": {"$arrayElemAt": ["$interview_data._id", 0]}},  # Added for analytics
            "screening_id": {"$toString": "$screening_id"},
            "proctoring_warning_count": "$proctoring_warning_count"
        }}
    ]
    
    enriched_candidates = await db.applications.aggregate(pipeline).to_list(length=1000)
    
    # 3. Enrich with Job Titles
    for candidate in enriched_candidates:
        candidate["job_title"] = job_map.get(candidate.get("job_id"), "Unknown Job")

    # Sanitize response
    def sanitize(obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, list):
            return [sanitize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        return obj
        
    sanitized_candidates = sanitize(enriched_candidates)
    
    return {"success": True, "candidates": sanitized_candidates}


