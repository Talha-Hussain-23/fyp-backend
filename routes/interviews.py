"""
Interview Routes (Async)
Endpoints for interview management, question generation, and evaluation
"""
from fastapi import APIRouter, Depends, HTTPException, Body, Request, BackgroundTasks
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone
import structlog

from schemas import (
    InterviewSession, 
    InterviewResponse, 
    EvaluationResult
)
from utils import (
    get_db, 
    ForbiddenError,
    NotFoundError
)
from core.auth import get_current_user
from services.interview.core import submit_response_fast, evaluate_and_score_background, start_interview as service_start_interview, _sync_interview_results_to_application
from services.infrastructure.transaction_service import TransactionService
from core.rate_limiter import limiter
from services.notification.notification_helper import (
    notify_interview_scheduled,
    notify_status_update
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/{interview_id}/start")
@limiter.limit("30/minute")
async def start_interview(
    request: Request,
    interview_id: str,
    db = Depends(get_db)
):
    """Initialize interview session explicitly (Async)"""
    try:
        result = await service_start_interview(interview_id, db, start_session=True)
        if "error" in result:
             raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Failed to start interview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start interview")


@router.post("/{interview_id}/submit")
@limiter.limit("100/minute")
async def submit_answer(
    request: Request,
    interview_id: str,
    response: InterviewResponse,
    background_tasks: BackgroundTasks,
    db = Depends(get_db)
):
    """Submit answer — fast-ack with background async AI evaluation"""
    try:
        result = await submit_response_fast(interview_id, response, db)
        
        ack = result.get("ack", {})
        if ack.get("needs_background_eval"):
            background_tasks.add_task(
                evaluate_and_score_background,
                interview_id,
                ack["question_index"],
                ack["response_entry"],
                ack["question_obj"],
                ack["job_context"],
                db
            )
        elif ack.get("sync_required"):
            background_tasks.add_task(
                _sync_interview_results_to_application,
                interview_id,
                db
            )
        
        return result["response"]
    except Exception as e:
        logger.error("submission_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{interview_id}/evaluation-status")
@limiter.limit("120/minute")
async def get_evaluation_status(
    request: Request,
    interview_id: str,
    db = Depends(get_db)
):
    """Check background evaluation completion (Async)"""
    try:
        interview = await db.interviews.find_one(
            {"_id": ObjectId(interview_id)},
            {"evaluation_pending": 1, "completion_pending": 1, "scores": 1, 
             "is_completed": 1, "avg_score": 1, "final_score": 1, "status": 1}
        )
        if not interview: raise HTTPException(status_code=404, detail="Interview not found")
        
        return {
            "evaluation_pending": interview.get("evaluation_pending", False),
            "completion_pending": interview.get("completion_pending", False),
            "scores_count": len(interview.get("scores", [])),
            "is_completed": interview.get("is_completed", False),
            "status": interview.get("status", "in_progress"),
            "final_score": interview.get("final_score"),
            "avg_score": interview.get("avg_score"),
        }
    except HTTPException: raise
    except Exception as e:
        logger.error("evaluation_status_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{interview_id}/results")
async def get_results(
    interview_id: str,
    token: Optional[str] = None,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get interview results with detailed scores (Async)"""
    try:
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview: raise HTTPException(status_code=404, detail="Interview not found")
        
        has_access = False
        if current_user:
            if str(interview.get("candidate_id")) == current_user.id or \
               str(interview.get("recruiter_id")) == current_user.id:
                has_access = True
        elif token:
            valid_tokens = [interview.get("access_token"), interview.get("interview_token")]
            if token in valid_tokens: has_access = True
        
        if not has_access: raise HTTPException(status_code=403, detail="Access denied")
        if not interview.get("is_completed"): raise HTTPException(status_code=400, detail="Interview not completed")
        
        return {
            "interview_id": interview_id,
            "status": interview.get("status"),
            "is_completed": interview.get("is_completed"),
            "completed_at": interview.get("completed_at"),
            "score_breakdown": interview.get("score_breakdown"),
            "violation_log": interview.get("violation_log", []),
            "total_strikes": interview.get("total_strikes", 0),
            "final_score": interview.get("final_score"),
            "avg_score": interview.get("avg_score")
        }
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Failed to get results: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve results")


@router.get("/{interview_id}")
@limiter.limit("60/minute")
async def get_interview(
    request: Request,
    interview_id: str,
    token: Optional[str] = None,
    db = Depends(get_db)
):
    """Get interview data — Unified Start/Resume (Async)"""
    try:
        check = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not check: raise NotFoundError("Interview not found")

        valid_tokens = [t for t in [check.get("access_token"), check.get("interview_token")] if t]
        if not token or token not in valid_tokens:
            raise ForbiddenError("Access denied: Invalid token")
        
        if check.get('session_locked'):
            raise ForbiddenError(f"Interview access denied: {check.get('session_lock_reason')}")
        
        if check.get("is_completed"):
             check["id"] = str(check.pop("_id"))
             # Ensure related IDs are strings
             for key in ["resume_id", "jd_id", "recruiter_id", "candidate_id"]:
                 if check.get(key):
                     check[key] = str(check[key])
             return check

        result = await service_start_interview(interview_id, db, start_session=False)
        return result
    except (NotFoundError, ForbiddenError) as e: raise e
    except Exception as e:
        logger.error(f"Get interview failed: {e}")
        raise HTTPException(500, "Internal error")


@router.post("/{interview_id}/terminate")
async def terminate_interview(
    interview_id: str,
    body: dict = Body(...),
    db = Depends(get_db)
):
    """Terminate interview and finalize scoring (Async)"""
    try:
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview: raise NotFoundError("Interview not found")
        
        reason = body.get("reason", "Manual termination")
        # For simplicity, we assume all responses are already graded by background worker 
        # or were MCQ. If not, we'd trigger a final re-eval here.
        
        scores = interview.get("scores", [])
        final_score = interview.get("avg_score", 0)
        
        # If final_score is 0 but there are scores, calculate it dynamically
        if final_score == 0 and scores:
            final_score = round(sum(s.get("score", 0) for s in scores) / len(scores), 1)
        
        result = await TransactionService.terminate_interview_safe(
            interview_id=interview_id,
            reason=reason,
            final_score=final_score,
            scores=scores,
            db=db
        )
        return result
    except Exception as e:
        logger.error(f"Termination failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/{interview_id}/violation")
async def log_proctoring_violation(
    interview_id: str,
    violation: dict = Body(...),
    db = Depends(get_db)
):
    """Log a proctoring violation (Async)"""
    # Logic delegated to WarningManager (requires async conversion if DB used)
    # Assuming WarningManager is updated or handles motor
    from app.proctoring.warning_manager import WarningManager, ViolationType
    wm = WarningManager(db)
    # record_violation should be async
    result = await wm.record_violation(interview_id, ViolationType.TAB_SWITCHED, violation)
    return result
