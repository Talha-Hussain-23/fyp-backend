"""
Public Candidate Routes
Endpoints for candidates to view jobs and apply
"""
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form, BackgroundTasks
from typing import Optional, List
from bson import ObjectId
from datetime import datetime

from schemas import JDResponse, PaginatedResponse
from utils import get_db, logger
from utils.validators import validate_object_id, validate_email  # ✅ Security
from services.processing.core import process_resume
from services.automation.screening import screen_candidate
from services.email.email_service import send_application_submitted_email
from core.models import create_application_document

router = APIRouter()

async def process_application_background(
    job_id: str,
    resume_id: str,
    application_id: str,
    name: str,
    email: str,
    file_bytes: bytes,
    file_name: str,
    content_type: str,
    db
):
    """Heavy processing done in background: OCR, Scoring, Emails, Notifications"""
    try:
        # 1. Process resume (OCR, Features, Embedding)
        # Mocking an UploadFile object for process_resume
        from fastapi import UploadFile
        import io
        
        file = UploadFile(
            filename=file_name,
            file=io.BytesIO(file_bytes),
            size=len(file_bytes),
            headers={"content-type": content_type}
        )
        
        # This is where the heavy work happens
        resume_result = await process_resume(file, db)
        
        # Update resume record with the pre-generated ID
        await db.resumes.update_one(
            {"_id": ObjectId(resume_id)},
            {"$set": {
                "text": resume_result["text"],
                "features": resume_result["features"],
                "processed_at": datetime.utcnow().isoformat()
            }}
        )

        # 2. Match Score & Screening
        ai_match_score = 0
        match_score_breakdown = {}
        screening_id = None
        
        job = await db.jds.find_one({"_id": ObjectId(job_id)})
        if job:
            try:
                jd_text = job.get("description", "")
                if job.get("title"):
                    jd_text = f"{job['title']}\n{jd_text}"
                    
                screening_result = await screen_candidate(
                    candidate_id=resume_id,
                    job_id=job_id,
                    resume_text=resume_result.get("text", ""),
                    resume_features=resume_result.get("features", {}),
                    jd_text=jd_text,
                    db=db
                )
                
                if screening_result.get("success"):
                    ai_match_score = screening_result.get("matchScore", 0)
                    match_score_breakdown = screening_result.get("screening", {}).get("matchScoreBreakdown", {})
                    if screening_result.get("screening", {}).get("_id"):
                        screening_id = str(screening_result["screening"]["_id"])
            except Exception as e:
                logger.error(f"Background Scoring failed: {e}")

        # 3. Update application record
        await db.applications.update_one(
            {"_id": ObjectId(application_id)},
            {"$set": {
                "ai_match_score": ai_match_score,
                "match_score_breakdown": match_score_breakdown,
                "screening_id": screening_id,
                "status": "New", # Update from 'Processing'
                "resume_id": ObjectId(resume_id)
            }}
        )
        
        # 4. Send confirmation email
        try:
            await send_application_submitted_email(
                to_email=email,
                candidate_name=name,
                job_title=job.get("title", "Position") if job else "Position",
                db=db
            )
        except Exception as e:
            logger.error(f"Background Email failed: {e}")
            
        # 5. Create notification for recruiter
        try:
            from services.notification.notification_service import create_application_notification
            from app.proctoring.socketio_server import send_notification_to_user
            
            if job and job.get("recruiter_id"):
                recruiter_id = str(job.get("recruiter_id"))
                notification_id = await create_application_notification(
                    db=db,
                    recruiter_id=recruiter_id,
                    job_title=job.get("title", "Position"),
                    candidate_name=name,
                    job_id=job_id
                )
                
                notification_doc = await db.notifications.find_one({"_id": ObjectId(notification_id)})
                if notification_doc:
                    notification_doc["id"] = str(notification_doc.pop("_id"))
                    await send_notification_to_user(recruiter_id, notification_doc)
        except Exception as e:
            logger.error(f"Background Notification failed: {e}")

        logger.info(f"✅ Background processing completed for application {application_id}")

    except Exception as e:
        logger.error(f"❌ Background processing failed for application {application_id}: {e}")
        # Update status to error if needed
        await db.applications.update_one(
            {"_id": ObjectId(application_id)},
            {"$set": {"status": "Error", "error_detail": str(e)}}
        )

@router.post("/jobs/{job_id}/apply")
async def apply_for_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    email: str = Form(...),
    file: UploadFile = File(...),
    db = Depends(get_db)
):
    """Submit a job application with resume (Optimized with BackgroundTasks)"""
    # ✅ SECURITY FIX: Validate inputs
    job_obj_id = validate_object_id(job_id, "Job ID")
    email = validate_email(email)
    
    # 1. Verify job exists
    job = await db.jds.find_one({"_id": job_obj_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # ✅ FIXED: Check for duplicate application (IDEMPOTENCY)
    existing_application = await db.applications.find_one({
        "job_id": job_id,
        "candidate_email": email
    })
    
    if existing_application:
        raise HTTPException(
            status_code=409,
            detail="You have already applied to this job. Check your email for confirmation."
        )
    
    # 2. Pre-generate IDs
    resume_id = ObjectId()
    application_id = ObjectId()
    
    # 3. Create initial application record immediately (Responsive UI)
    app_doc = create_application_document(
        job_id=job_id,
        resume_id=resume_id,
        candidate_name=name,
        candidate_email=email,
        status="Processing", # Indicating background work
        ai_match_score=0,
        match_score_breakdown={},
        screening_id=None
    )
    app_doc["_id"] = application_id
    
    # Create shell resume record
    from core.models import create_resume_document
    resume_doc = create_resume_document(
        candidate_name=name,
        email=email,
        text="", # To be filled in background
        features={},
        file_name=file.filename,
        file_type=file.content_type,
        embedding=[]
    )
    resume_doc["_id"] = resume_id

    try:
        await db.resumes.insert_one(resume_doc)
        await db.applications.insert_one(app_doc)
    except Exception as e:
        if "duplicate key" in str(e).lower() or "11000" in str(e):
            raise HTTPException(
                status_code=409,
                detail="Application already exists. This may be due to a duplicate submission."
            )
        raise

    # 4. Offload heavy work to background
    file_bytes = await file.read()
    background_tasks.add_task(
        process_application_background,
        job_id=job_id,
        resume_id=str(resume_id),
        application_id=str(application_id),
        name=name,
        email=email,
        file_bytes=file_bytes,
        file_name=file.filename,
        content_type=file.content_type,
        db=db
    )
    
    return {
        "success": True, 
        "message": "Application submitted! We are processing your resume in the background.", 
        "application_id": str(application_id)
    }

@router.get("/jobs", response_model=PaginatedResponse)
async def list_public_jobs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status_filter: str = Query("open", alias="status_filter"),
    sortBy: Optional[str] = None,
    db = Depends(get_db)
):
    """Public job listing (Async)"""
    query = {}
    
    # Handle status filtering - 'all' means no status filter
    if status_filter and status_filter.lower() != "all":
        query["status"] = status_filter.lower()
    
    if search:
        # Simple regex search if text index not available
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}}
        ]
        
    total = await db.jds.count_documents(query)
    
    # Handle sorting
    sort_field = "created_at"
    if sortBy == "title":
        sort_field = "title"
    
    cursor = db.jds.find(query).skip((page-1)*per_page).limit(per_page).sort(sort_field, -1)
    
    jobs = []
    async for job in cursor:
        job["id"] = str(job["_id"])
        del job["_id"]
        recruiter_id = job.get("recruiter_id", "")
        job["recruiter_id"] = str(recruiter_id)
        
        # Add recruiter name lookup
        if recruiter_id:
            try:
                recruiter = await db.users.find_one({"_id": ObjectId(recruiter_id)})
                job["recruiter_name"] = recruiter.get("name", "Unknown") if recruiter else "Unknown"
            except Exception:
                job["recruiter_name"] = "Unknown"
        else:
            job["recruiter_name"] = "Unknown"
        
        jobs.append(job)
        
    return {
        "success": True,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "items": jobs
    }

@router.get("/jobs/{job_id}", response_model=JDResponse)
async def get_public_job(job_id: str, db = Depends(get_db)):
    """Get public job details (Async)"""
    # ✅ SECURITY FIX: Validate ObjectId
    job_obj_id = validate_object_id(job_id, "Job ID")
    job = await db.jds.find_one({"_id": job_obj_id})
        
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job["id"] = str(job["_id"])
    del job["_id"]
    recruiter_id = job.get("recruiter_id", "")
    job["recruiter_id"] = str(recruiter_id)
    
    # Add recruiter name
    if recruiter_id:
        try:
            recruiter = await db.users.find_one({"_id": ObjectId(recruiter_id)})
            job["recruiter_name"] = recruiter.get("name", "Unknown") if recruiter else "Unknown"
        except Exception:
            job["recruiter_name"] = "Unknown"
    else:
        job["recruiter_name"] = "Unknown"
    
    return job

@router.get("/jobs/{job_id}/application-status")
async def check_application_status(
    job_id: str, 
    email: str = Query(..., description="Email address to check"),
    db = Depends(get_db)
):
    """Check if a candidate has already applied to a job (Async)"""
    # ✅ SECURITY FIX: Validate inputs
    job_obj_id = validate_object_id(job_id, "Job ID")
    email = validate_email(email)
    
    # Verify job exists
    job = await db.jds.find_one({"_id": job_obj_id})
        
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Check if application exists
    application = await db.applications.find_one({
        "job_id": job_id,
        "candidate_email": email
    })
    
    return {
        "success": True,
        "has_applied": application is not None,
        "application_id": str(application["_id"]) if application else None,
        "job_status": job.get("status", "open"),
        "application_status": application.get("status", "New") if application else None
    }

