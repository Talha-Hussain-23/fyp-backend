from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from bson import ObjectId
from datetime import datetime
from typing import Optional

from utils import (
    get_db, 
    logger,
    ForbiddenError,
    NotFoundError
)
from core.auth import get_current_user

router = APIRouter()


async def process_reclaim_background(
    reclaim_id: str,
    action: str,
    new_token: Optional[str],
    current_user_id: str,
    rejection_message: Optional[str],
    db
):
    """Heavy processing for reclaim: Question regeneration and Emails done in background"""
    try:
        reclaim = await db.reclaim_requests.find_one({"_id": ObjectId(reclaim_id)})
        if not reclaim:
            logger.error(f"Reclaim request {reclaim_id} not found in background")
            return

        job = await db.jds.find_one({"_id": ObjectId(reclaim.get("job_id"))})
        if not job:
            logger.error(f"Job not found for reclaim {reclaim_id}")
            return

        email_sent = False
        email_error = None

        if action == "approve":
            interview = await db.interviews.find_one({"_id": ObjectId(reclaim["interview_id"])})
            if not interview:
                logger.error(f"Interview not found for reclaim {reclaim_id}")
                return
            
            # ✅ Process Approval (Questions + DB Updates)
            async with await db.client.start_session() as session:
                try:
                    async with session.start_transaction():
                        # 1. Regenerate Questions
                        resume = await db.resumes.find_one({"_id": ObjectId(interview["resume_id"])}, session=session)
                        resume_text = resume.get("text", "") if resume else ""
                        
                        final_questions = []
                        final_sections = []
                        
                        if interview.get("sections") or job.get("interview_config"):
                            # REGENERATE SECTIONS
                            logger.info(f"Regenerating SECTIONED interview questions (Background) for reclaim {reclaim_id}")
                            interview_config = job.get("interview_config") or {"sections": []}
                            config_sections = interview_config.get("sections", [])
                            
                            if not config_sections and interview.get("sections"):
                                 config_sections = interview.get("sections")
    
                            sections = []
                            from services.interview.questions.generator import generate_questions
                            
                            for section_cfg in config_sections:
                                if not section_cfg.get("enabled", True): continue
                                
                                s_type = section_cfg.get("type", "Descriptive")
                                s_num = section_cfg.get("num_questions", 5)
                                s_dif = section_cfg.get("difficulty", "Moderate")
                                
                                q_list = await generate_questions(
                                    jd=job.get("description", ""),
                                    resume_text=resume_text,
                                    num_questions=s_num,
                                    difficulty_level=s_dif,
                                    question_type=s_type,
                                    ai_instructions=job.get("ai_instructions"),
                                    job_title=job.get("title", "Position")
                                )
                                
                                new_section = section_cfg.copy()
                                new_section["questions"] = q_list
                                new_section["current_question_index"] = 0
                                new_section["responses"] = []
                                new_section["status"] = "not_started"
                                sections.append(new_section)
                            
                            final_sections = sections
                            final_questions = [] 
                            
                        else:
                            # REGENERATE LEGACY
                            logger.info(f"Regenerating LEGACY interview questions (Background) for reclaim {reclaim_id}")
                            from services.interview.questions.generator import generate_questions
                            final_questions = await generate_questions(
                                jd=job.get("description", ""),
                                resume_text=resume_text,
                                num_questions=interview.get("num_questions", 5),
                                difficulty_level=interview.get("difficulty_level", "Medium"),
                                question_type=interview.get("question_type", "Descriptive"),
                                ai_instructions=job.get("ai_instructions"),
                                job_title=job.get("title", "Position")
                            )

                        # 2. Update Interview — Full session isolation reset
                        update_set = {
                            "access_token": new_token,
                            "is_completed": False,
                            "is_terminated": False,
                            "status": "pending",
                            "state": "CREATED",
                            "reclaimed": True,
                            "reclaimed_at": datetime.utcnow().isoformat(),
                            "responses": [],
                            "scores": [],
                            "avg_score": 0,
                            "final_score": 0,
                            # --- Proctoring State Reset (CRITICAL) ---
                            "proctoring_warning_count": 0,
                            "proctoring_violations": [],
                            "total_strikes": 0,           # FIX: was "total_striites" (typo) — wrong field was being reset!
                            # --- Evaluation State Reset ---
                            "evaluation_pending": False,   # FIX: was missing — could re-trigger stale background eval
                            "completion_pending": False,   # FIX: was missing — could lock UI in 'evaluating' state
                            # --- Session & Navigation Reset ---
                            "current_question_index": 0,
                            "session_locked": False,
                        }
                        
                        if final_sections:
                            update_set["sections"] = final_sections
                            update_set["questions"] = []
                        else:
                            update_set["questions"] = final_questions
                            
                        await db.interviews.update_one(
                            {"_id": ObjectId(reclaim["interview_id"])},
                            {
                                "$set": update_set,
                                "$unset": {
                                    # Timing fields
                                    "termination_reason": "",
                                    "terminated_at": "",
                                    "close_reason": "",
                                    "question_expires_at": "",
                                    "question_started_at": "",
                                    "question_duration": "",
                                    "started_at": "",
                                    "interview_expires_at": "",
                                    # Session lock fields
                                    "session_lock_reason": "",
                                    "session_lock_metadata": "",
                                    # ML/Scoring metadata (FIX: these persist from old session)
                                    "score_breakdown": "",
                                    "overall_score": "",
                                    "first_violation_at": "",
                                    "last_violation_at": "",
                                }
                            },
                            session=session
                        )

                        
                        if reclaim.get("job_id") and reclaim.get("candidate_email"):
                            await db.applications.update_one(
                                {
                                    "job_id": reclaim["job_id"], 
                                    "candidate_email": reclaim["candidate_email"]
                                },
                                {"$set": {
                                    "status": "Interviewing",
                                    "interview_status": "Scheduled",
                                    # FIX: Do NOT reset interview_score to 0 here.
                                    # Zeroing it causes the recruiter dashboard to show 0 permanently
                                    # even after the new interview completes and is scored.
                                    # The score sync (_sync_interview_results_to_application) will
                                    # update this field correctly once background evaluation finishes.
                                    "interview_score": None  # Null = 'not yet scored' (dashboard shows N/A vs 0)
                                }},
                                session=session
                            )
                except Exception as e:
                    logger.error(f"❌ Background transaction failed for reclaim {reclaim_id}: {e}")
                    return
                finally:
                    await session.end_session()

            # 3. Send Approval Email
            try:
                from services.email.email_service import send_reclaim_approved_email
                recruiter = await db.users.find_one({"_id": ObjectId(current_user_id)})
                candidate_email = reclaim.get("candidate_email")
                
                if interview and job:
                    await send_reclaim_approved_email(
                        to_email=candidate_email,
                        candidate_name=reclaim.get("candidate_name", "Candidate"),
                        job_title=job.get("title", "Position"),
                        interview_id=reclaim["interview_id"],
                        interview_token=new_token,
                        recruiter_name=recruiter.get("name") if recruiter else "Smart Recruiter AI Team",
                        company_name=recruiter.get("organization") if recruiter else "Smart Recruiter AI",
                        db=db
                    )
                    email_sent = True
            except Exception as e:
                logger.error(f"❌ Background Approval Email failed: {e}")
                email_error = str(e)
        
        elif action == "reject":
            # Send Rejection Email
            try:
                from services.email.email_service import send_reclaim_rejected_email
                recruiter = await db.users.find_one({"_id": ObjectId(current_user_id)})
                
                await send_reclaim_rejected_email(
                    to_email=reclaim.get("candidate_email"),
                    candidate_name=reclaim.get("candidate_name", "Candidate"),
                    job_title=job.get("title", "Position"),
                    rejection_message=rejection_message or "Your reclaim request has been reviewed and unfortunately cannot be approved at this time.",
                    recruiter_name=recruiter.get("name") if recruiter else "Smart Recruiter AI Team",
                    company_name=recruiter.get("organization") if recruiter else "Smart Recruiter AI",
                    db=db
                )
                email_sent = True
            except Exception as e:
                logger.error(f"❌ Background Rejection Email failed: {e}")
                email_error = str(e)

        # Update final result with email status
        await db.reclaim_requests.update_one(
            {"_id": ObjectId(reclaim_id)},
            {"$set": {
                "email_sent": email_sent,
                "email_error": email_error
            }}
        )
        logger.info(f"✅ Background processing completed for reclaim {reclaim_id}")

    except Exception as e:
        logger.error(f"❌ Background processing failed for reclaim {reclaim_id}: {e}")

@router.get("/interview-info")
async def get_interview_info_for_reclaim(
    interview_id: str = Query(..., description="The interview ID from the email link"),
    token: str = Query(..., description="The interview token from the email link"),
    db = Depends(get_db)
):
    """
    Public endpoint: fetches candidate name & email for a given interview_id + token.
    Used by InterviewReclaim.js to auto-fill the reclaim form fields.
    No auth required — token acts as the access credential.
    """
    try:
        if not ObjectId.is_valid(interview_id):
            raise HTTPException(status_code=400, detail="Invalid interview ID format")
        
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        # Verify the token matches (interview_token OR access_token after a previous reclaim)
        valid_tokens = [t for t in [interview.get("access_token"), interview.get("interview_token")] if t]
        if not token or token not in valid_tokens:
            raise HTTPException(status_code=403, detail="Invalid or expired interview token")
        
        # Step 1: Try to fetch from Application (Most reliable source of truth)
        candidate_name = ""
        candidate_email = ""
        resume_id = interview.get("resume_id")
        jd_id = interview.get("jd_id")
        
        if resume_id and jd_id:
            try:
                app = await db.applications.find_one({
                    "job_id": str(jd_id), 
                    "resume_id": str(resume_id)
                })
                if app:
                    candidate_name = app.get("candidate_name", "")
                    candidate_email = app.get("candidate_email", "")
            except Exception as e:
                logger.warning(f"Failed to fetch application for interview info: {e}")
                pass
                
        # Step 2: Fallback to Resumes collection if not found in applications
        if not candidate_email and resume_id:
            try:
                resume = await db.resumes.find_one({"_id": ObjectId(resume_id)})
                if resume:
                    candidate_name = candidate_name or resume.get("candidate_name", "")
                    candidate_email = resume.get("email", "")
            except Exception as e:
                logger.warning(f"Failed to fetch resume for interview info: {e}")
                pass
                
        # Step 3: CRITICAL PRIVACY FIX
        # If the recruiter manually created the interview/uploaded the resume, 
        # the AI parser might have incorrectly grabbed the recruiter's own email/name,
        # or it defaulted to the uploader's session email.
        # We MUST ensure we never auto-fill the recruiter's info for the candidate!
        if candidate_email and jd_id:
            try:
                job = await db.jds.find_one({"_id": ObjectId(jd_id)})
                if job and job.get("recruiter_id"):
                    recruiter = await db.users.find_one({"_id": ObjectId(job["recruiter_id"])})
                    if recruiter and recruiter.get("email") and recruiter["email"].lower() == candidate_email.lower():
                        logger.warning(f"Prevented auto-filling recruiter's email ({candidate_email}) on candidate reclaim form.")
                        candidate_email = ""  # Wipe it out
                        # Also wipe the name if it matches to be extra safe
                        if recruiter.get("name") and recruiter["name"].lower() == candidate_name.lower():
                            candidate_name = ""
            except Exception as e:
                logger.warning(f"Failed to cross-check against recruiter email: {e}")
                pass
        
        return {
            "success": True,
            "candidate_name": candidate_name,
            "candidate_email": candidate_email,
            "interview_id": interview_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch interview info for reclaim: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch interview info")

@router.get("/")
async def get_reclaim_requests(
    status_filter: str = Query("Pending"),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get reclaim requests for the recruiter's jobs"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can access reclaim requests")
    
    try:
        # Get recruiter's job IDs (Awaited)
        recruiter_jobs = await db.jds.find({"recruiter_id": current_user.id}).to_list(length=1000)
        job_ids = [str(job["_id"]) for job in recruiter_jobs]
        
        # Build query
        query = {"job_id": {"$in": job_ids}}
        if status_filter and status_filter.lower() != "all":
            query["status"] = status_filter
        
        # Get reclaim requests
        cursor = db.reclaim_requests.find(query).sort("created_at", -1)
        
        reclaim_requests = []
        async for req in cursor:
            req["reclaim_id"] = str(req.pop("_id"))
            req["requested_at"] = req.get("created_at")
            
            # Get interview and candidate info (Awaited)
            if req.get("interview_id"):
                interview = await db.interviews.find_one({"_id": ObjectId(req["interview_id"])})
                if interview:
                    if not req.get("candidate_name"):
                        req["candidate_name"] = interview.get("candidate_name", "Unknown")
                    if not req.get("candidate_email"):
                        req["candidate_email"] = interview.get("candidate_email", "")
                    
                    req["time_spent_seconds"] = interview.get("time_used", 0)
                    req["initial_interview_started_at"] = interview.get("started_at")
                    req["detected_reason"] = interview.get("termination_reason")
            
            # Get job info (Awaited)
            if req.get("job_id"):
                job = await db.jds.find_one({"_id": ObjectId(req["job_id"])})
                req["job_title"] = job.get("title", "Unknown") if job else "Unknown"
            
            if req.get("handled_at"):
                req["processed_at"] = req.pop("handled_at")
            
            reclaim_requests.append(req)
        
        return {
            "success": True,
            "reclaim_requests": reclaim_requests
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch reclaim requests: {e}")
        return {
            "success": True,
            "reclaim_requests": []
        }

@router.post("/")
async def create_reclaim_request(
    body: dict = Body(...),
    db = Depends(get_db)
):
    """Create a new reclaim request"""
    try:
        interview_id = body.get("interview_id")
        interview_token = body.get("interview_token")
        candidate_name = body.get("candidate_name")
        candidate_email = body.get("candidate_email")
        reason = body.get("reason", "")
        
        logger.info(f"Reclaim request received for interview: {interview_id}")
        
        if not interview_id:
            raise HTTPException(status_code=400, detail="Interview ID is required")
        if not candidate_email:
            raise HTTPException(status_code=400, detail="Email is required")
        if not candidate_name:
            raise HTTPException(status_code=400, detail="Name is required")
        
        try:
            interview_obj_id = ObjectId(interview_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid interview ID format")
        
        interview = await db.interviews.find_one({"_id": interview_obj_id})
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        # CRITICAL FIX: Check BOTH access_token and interview_token
        if interview_token:
            valid_tokens = [t for t in [interview.get("access_token"), interview.get("interview_token")] if t]
            if interview_token not in valid_tokens:
                logger.warning(f"Token mismatch for interview {interview_id}. Provided: {interview_token[:10]}..., Valid: {[t[:10] + '...' for t in valid_tokens]}")
                raise HTTPException(status_code=403, detail="Invalid interview token")
        
        existing_request = await db.reclaim_requests.find_one({
            "interview_id": interview_id,
            "status": "Pending"
        })
        
        if existing_request:
            return {
                "success": False,
                "message": "A pending reclaim request already exists"
            }
        
        reclaim_doc = {
            "interview_id": interview_id,
            "job_id": interview.get("jd_id"),
            "candidate_name": candidate_name or interview.get("candidate_name", "Unknown"),
            "candidate_email": candidate_email,
            "reason": reason,
            "status": "Pending",
            "created_at": datetime.utcnow().isoformat(),
            "handled_by": None,
            "handled_at": None
        }
        
        result = await db.reclaim_requests.insert_one(reclaim_doc)
        
        return {
            "success": True,
            "message": "Reclaim request submitted successfully",
            "reclaim_id": str(result.inserted_id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create reclaim request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{reclaim_id}/action") 
async def handle_reclaim_action(
    reclaim_id: str,
    background_tasks: BackgroundTasks,
    body: dict = Body(...),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Approve or reject a reclaim request (Optimized with BackgroundTasks)"""
    if not current_user.is_recruiter:
        raise ForbiddenError("Only recruiters can handle reclaim requests")
    
    action = body.get("action", "").lower()
    if action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
    
    try:
        reclaim = await db.reclaim_requests.find_one({"_id": ObjectId(reclaim_id)})
        if not reclaim:
            raise NotFoundError("Reclaim request not found")
        
        job = await db.jds.find_one({"_id": ObjectId(reclaim.get("job_id"))})
        if not job or str(job.get("recruiter_id")) != current_user.id:
            raise ForbiddenError("You do not have permission to handle this request")
        
        new_status = "Approved" if action == "approve" else "Rejected"
        
        # 1. Update status immediately for responsive UI
        update_data = {
            "status": new_status,
            "handled_by": current_user.id,
            "handled_at": datetime.utcnow().isoformat()
        }
        
        import secrets
        new_token = secrets.token_urlsafe(32) if action == "approve" else None
        
        if action == "reject" and body.get("rejection_message"):
            update_data["rejection_message"] = body["rejection_message"]
        
        await db.reclaim_requests.update_one(
            {"_id": ObjectId(reclaim_id)},
            {"$set": update_data}
        )

        # 2. Offload heavy work to background
        background_tasks.add_task(
            process_reclaim_background,
            reclaim_id=reclaim_id,
            action=action,
            new_token=new_token,
            current_user_id=current_user.id,
            rejection_message=body.get("rejection_message"),
            db=db
        )

        return {
            "success": True,
            "message": f"Reclaim request {new_status.lower()}! Processing in background.",
            "status": new_status
        }
        
    except (HTTPException, ForbiddenError, NotFoundError):
        raise
    except Exception as e:
        logger.error(f"Failed to handle reclaim request: {e}")
        raise HTTPException(status_code=500, detail=str(e))
