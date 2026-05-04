from bson import ObjectId
from core.events import event_bus
from core.event_schemas import InterviewCompletedEvent, ReclaimApprovedEvent
from core.models import create_email_task_document
from services.notification.notification_service import create_notification
from services.email.email_worker import email_worker
from utils import get_db, logger

# --- Event Handlers ---

async def handle_interview_completed(event: InterviewCompletedEvent):
    """
    When interview completes:
    1. Notify Candidate (Screen)
    2. Notify Recruiter (Bell)
    3. Send Email Summary
    """
    try:
        logger.info(f"⚡ Handling Interview Completed: {event.interview_id}")
        db = await get_db()
        
        # 1. Fetch Interview & Job Details
        interview = await db.interviews.find_one({"_id": ObjectId(event.interview_id)})
        if not interview:
            logger.error(f"Interview {event.interview_id} not found")
            return

        job = await db.jds.find_one({"_id": ObjectId(interview["jd_id"])})
        if not job:
            logger.error(f"Job not found for interview {event.interview_id}")
            return
            
        recruiter_id = job["recruiter_id"]
        
        # Fetch candidate name
        resume = await db.resumes.find_one({"_id": ObjectId(interview["resume_id"])})
        candidate_name = resume.get("candidate_name") if resume else "Candidate"

        # 2. Generate Real-time Analytics (Awaited)
        from services.analytics.analytics import generate_candidate_profile
        stats = await generate_candidate_profile(event.interview_id, db)
        
        integrity_metrics = stats.get("integrity_metrics", {})
        integrity = integrity_metrics.get("integrity_score", 0)
        
        performance_metrics = stats.get("performance_metrics", {})
        final_score = performance_metrics.get("overall_score", {}).get("value", 0)

        # 3. Notify Recruiter (Persistent + Socket) - Awaited
        await create_notification(
            db=db,
            user_id=recruiter_id,
            title="Interview Completed",
            message=f"{candidate_name} finished interview for {job['title']}.\nScore: {final_score}% | Integrity: {integrity}%",
            notification_type="info" if integrity > 80 else "warning",
            link=f"/dashboard/candidates?interview_id={event.interview_id}",
            metadata={"interview_id": event.interview_id, "score": final_score, "integrity": integrity}
        )
        logger.info(f"🔔 Notified Recruiter {recruiter_id} of completion")

    except Exception as e:
        logger.error(f"Error handling interview completion: {e}")

async def handle_reclaim_approved(event: ReclaimApprovedEvent):
    """
    When reclaim is approved:
    1. Send Email to Candidate (High Priority)
    2. Notify Candidate (Bell)
    """
    try:
        logger.info(f"⚡ Handling Reclaim Approved: {event.interview_id}")
        db = await get_db()
        
        # 1. Queue Email (Robust DB-backed)
        # Fetch candidate email from interview/application
        interview = await db.interviews.find_one({"_id": ObjectId(event.interview_id)})
        candidate_email = interview.get("candidate_email") if interview else None
        
        if not candidate_email:
            # Fallback to job application if missing in interview
            application = await db.applications.find_one({"job_id": interview.get("job_id"), "candidate_name": interview.get("candidate_name")})
            candidate_email = application.get("candidate_email") if application else "candidate@example.com"
        
        task = create_email_task_document(
            to_email=candidate_email,
            subject="Interview Reclaim Approved - Action Required",
            template_name="reclaim_approved",
            template_data={"interview_id": event.interview_id}
        )
        
        # Insert into queue (Awaited)
        await db.email_queue.insert_one(task)
        logger.info(f"Queued Reclaim Email for {event.interview_id}")
        
        # 2. Real-time Notification (Awaited)
        await create_notification(
            db=db,
            user_id=event.candidate_id,
            title="Interview Reopened",
            message="Your reclaim request was approved. You can resume your interview now.",
            notification_type="success",
            link=f"/interview/{event.interview_id}"
        )

    except Exception as e:
        logger.error(f"Error handling reclaim approval: {e}")

# --- Registration ---

def register_event_handlers():
    """Call this on startup to wire up listeners"""
    event_bus.subscribe("INTERVIEW_COMPLETED", handle_interview_completed)
    event_bus.subscribe("RECLAIM_APPROVED", handle_reclaim_approved)
    logger.info("✅ Event Handlers Registered")
