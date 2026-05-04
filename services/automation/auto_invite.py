"""
Automatic Interview Invitation System
Automatically ranks applicants and sends interview invitations based on invite_rule
"""

import os
from typing import Dict, List, Optional
from datetime import datetime, timezone
from bson import ObjectId
from pymongo.database import Database
from services.ai.embeddings import match_resume_to_job, cosine_similarity
import secrets
import logging

logger = logging.getLogger(__name__)


async def rank_applicants_by_embeddings(job_id: str, db: Database) -> List[Dict]:
    """
    Rank all applicants for a job using LLM embeddings and cosine similarity (Async)
    Returns sorted list of applicants with match scores
    """
    try:
        # Get job
        job = await db.jds.find_one({"_id": ObjectId(job_id)})
        if not job:
            logger.error(f"Job {job_id} not found")
            return []
        
        # Get job embedding
        job_embedding = job.get("embedding")
        if not job_embedding:
            logger.warning(f"Job {job_id} has no embedding, cannot rank")
            return []
        
        # Get all applications for this job
        applications = await db.applications.find({"job_id": job_id}).to_list(length=1000)
        if not applications:
            logger.info(f"No applications found for job {job_id}")
            return []
        
        ranked_applicants = []
        
        for app in applications:
            resume_id = app.get("resume_id")
            if not resume_id:
                continue
            
            # Get resume
            resume = await db.resumes.find_one({"_id": ObjectId(resume_id)})
            if not resume:
                continue
            
            # Get resume embedding
            resume_embedding = resume.get("embedding")
            if not resume_embedding:
                logger.warning(f"Resume {resume_id} has no embedding, skipping")
                continue
            
            # Calculate match score (assuming this is sync and fast, or wrap if needed)
            match_score = match_resume_to_job(resume_embedding, job_embedding)
            
            ranked_applicants.append({
                "application_id": str(app["_id"]),
                "resume_id": resume_id,
                "candidate_name": app.get("candidate_name", resume.get("candidate_name", "Unknown")),
                "candidate_email": app.get("candidate_email", resume.get("email", "No email")),
                "match_score": match_score,
                "status": app.get("status", "New")
            })
        
        # Sort by match score (descending)
        ranked_applicants.sort(key=lambda x: x["match_score"], reverse=True)
        
        # Update match scores in applications
        for applicant in ranked_applicants:
            await db.applications.update_one(
                {"_id": ObjectId(applicant["application_id"])},
                {"$set": {"ai_match_score": applicant["match_score"]}}
            )
        
        return ranked_applicants
    
    except Exception as e:
        logger.error(f"Error ranking applicants: {e}")
        return []


def get_invite_count(invite_rule: str, invite_rule_n: Optional[int], total_applicants: int) -> int:
    """
    Determine how many applicants to invite based on invite_rule
    Returns the number of applicants to invite
    """
    if invite_rule == "All":
        return total_applicants
    elif invite_rule == "Top 5":
        return min(5, total_applicants)
    elif invite_rule == "Top 10":
        return min(10, total_applicants)
    elif invite_rule == "Top N" and invite_rule_n:
        return min(invite_rule_n, total_applicants)
    else:
        # Default to Top 10
        return min(10, total_applicants)


async def auto_send_interview_invitations(job_id: str, db: Database) -> Dict:
    """
    Automatically rank applicants and send interview invitations based on job's invite_rule (Async)
    This is ONLY called when job status is changed to "closed"
    """
    try:
        # Get job
        job = await db.jds.find_one({"_id": ObjectId(job_id)})
        if not job:
            return {"success": False, "error": "Job not found"}
        
        # IMPORTANT: Only send invitations when job is closed
        job_status = job.get("status", "open")
        if job_status != "closed":
            logger.info(f"Job {job_id} is not closed (status: {job_status}), skipping auto-invite")
            return {"success": False, "error": f"Job must be closed to send interview invitations"}
        
        invite_rule = job.get("invite_rule", "Top 10")
        invite_rule_n = job.get("invite_rule_n")
        
        # Check if auto-invite is already processed
        auto_invite_processed = job.get("auto_invite_processed", False)
        if auto_invite_processed:
            logger.info(f"Auto-invite already processed for job {job_id}")
            return {"success": True, "message": "Auto-invite already processed", "skipped": True}
        
        # Rank all applicants
        ranked_applicants = await rank_applicants_by_embeddings(job_id, db)
        if not ranked_applicants:
            return {"success": True, "message": "No applicants to rank", "invited": 0}
        
        # Determine how many to invite
        invite_count = get_invite_count(invite_rule, invite_rule_n, len(ranked_applicants))
        applicants_to_invite = ranked_applicants[:invite_count]
        
        # Get job details
        num_questions = job.get("num_questions", 5)
        difficulty_level = job.get("difficulty_level", "Medium")
        job_title = job.get("title", "Position")
        recruiter_id = job.get("recruiter_id")
        
        # Get recruiter info
        recruiter = None
        if recruiter_id:
            recruiter = await db.users.find_one({"_id": ObjectId(recruiter_id)})
        
        invited_count = 0
        errors = []
        
        # Create interviews and send invitations
        for applicant in applicants_to_invite:
            try:
                # Check if interview already exists
                existing_interview = await db.interviews.find_one({
                    "jd_id": job_id,
                    "resume_id": applicant["resume_id"]
                })
                
                interview_id = None
                interview_token = None
                
                if existing_interview:
                    interview_id = str(existing_interview["_id"])
                    interview_token = existing_interview.get("interview_token")
                    
                    # Check if invitation was sent
                    existing_email = await db.emails_sent.find_one({
                        "job_id": job_id,
                        "interview_id": interview_id,
                        "candidate_email": applicant['candidate_email'],
                        "email_type": "interview_invitation",
                        "status": "sent"
                    })
                    
                    if existing_email:
                        continue
                else:
                    # Create new interview
                    from services.interview import generate_questions
                    from core.models import create_interview_document
                    
                    # Get resume text
                    resume = await db.resumes.find_one({"_id": ObjectId(applicant["resume_id"])})
                    resume_text = resume.get("text", "") if resume else ""
                    
                    # Generate questions (Async)
                    try:
                        questions = await generate_questions(job.get("description", ""), resume_text, num_questions, difficulty_level, job_title=job_title)
                    except Exception as e:
                        logger.warning(f"Failed to generate questions: {e}")
                        questions = [f"Question {i+1}: Tell us about your experience." for i in range(num_questions)]
                    
                    # Create interview
                    interview_token = secrets.token_urlsafe(32)
                    interview_doc = create_interview_document(
                        jd_id=job_id,
                        resume_id=applicant["resume_id"],
                        questions=questions,
                        interview_token=interview_token,
                        started_at=datetime.now(timezone.utc).isoformat()
                    )
                    
                    result = await db.interviews.insert_one(interview_doc)
                    interview_id = str(result.inserted_id)
                
                # Send interview invitation email
                try:
                    from services.email.email_service import send_interview_invitation_email
                    
                    recruiter_name = recruiter.get("name", recruiter.get("email", "Smart Recruiter AI Team")) if recruiter else "Smart Recruiter AI Team"
                    company_name = recruiter.get("organization", "Smart Recruiter AI") if recruiter else "Smart Recruiter AI"
                    
                    # Centralized email service call (Async)
                    await send_interview_invitation_email(
                        to_email=applicant['candidate_email'],
                        candidate_name=applicant['candidate_name'],
                        job_title=job_title,
                        interview_id=interview_id,
                        interview_token=interview_token,
                        recruiter_name=recruiter_name,
                        company_name=company_name,
                        user_id=recruiter_id,
                        db=db
                    )
                    
                    # Log email
                    await db.emails_sent.insert_one({
                        "job_id": job_id,
                        "application_id": applicant["application_id"],
                        "candidate_email": applicant['candidate_email'],
                        "candidate_name": applicant['candidate_name'],
                        "email_type": "interview_invitation",
                        "sent_at": datetime.now(timezone.utc).isoformat(),
                        "interview_id": interview_id,
                        "status": "sent"
                    })
                    
                    # Update application status
                    await db.applications.update_one(
                        {"_id": ObjectId(applicant["application_id"])},
                        {
                            "$set": {
                                "status": "invited",
                                "invited_at": datetime.now(timezone.utc).isoformat(),
                                "updated_at": datetime.now(timezone.utc).isoformat()
                            }
                        }
                    )
                    
                    invited_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to send interview email to {applicant['candidate_email']}: {e}")
                    errors.append(str(e))
            
            except Exception as e:
                logger.error(f"Error processing applicant {applicant.get('candidate_email')}: {e}")
                errors.append(str(e))
        
        # Mark job as auto-invite processed
        await db.jds.update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "auto_invite_processed": True,
                    "auto_invite_processed_at": datetime.now(timezone.utc).isoformat(),
                    "auto_invite_count": invited_count
                }
            }
        )
        
        return {
            "success": True,
            "message": f"Automatically invited {invited_count} applicants",
            "invited": invited_count,
            "total_ranked": len(ranked_applicants),
            "invite_rule": invite_rule,
            "errors": errors if errors else None
        }
    
    except Exception as e:
        logger.error(f"Error in auto_send_interview_invitations: {e}")
        return {"success": False, "error": str(e)}

