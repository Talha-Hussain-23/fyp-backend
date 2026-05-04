"""
Violations API Routes
Endpoints for recording and retrieving proctoring violations
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body, BackgroundTasks
from typing import Dict
from bson import ObjectId
import structlog

from utils import get_db
from core.rate_limiter import limiter
from app.proctoring.warning_manager import WarningManager, ViolationType
from services.interview.core import evaluate_terminated_interview_background

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/record")
@limiter.limit("100/minute")
async def record_violation(
    request: Request,
    background_tasks: BackgroundTasks,
    body: Dict = Body(...),
    db = Depends(get_db)
):
    """
    Record a proctoring violation
    
    Request body:
    {
        "interview_id": "string",
        "violation_type": "TAB_SWITCHED" | "CELL_PHONE" | ...,
        "metadata": {
            "confidence": 0.85,  # For YOLO detections
            "bbox": [x, y, w, h],  # Bounding box
            "duration": 5  # Violation duration in seconds
        }
    }
    
    Response:
    {
        "violation": {...},
        "total_strikes": 2,
        "max_strikes": 3,
        "should_terminate": false,
        "strikes_remaining": 1,
        "grace_applied": true
    }
    """
    
    try:
        interview_id = body.get("interview_id")
        violation_type_str = body.get("violation_type")
        metadata = body.get("metadata", {})
        
        # Validation
        if not interview_id:
            raise HTTPException(status_code=400, detail="interview_id is required")
        
        if not violation_type_str:
            raise HTTPException(status_code=400, detail="violation_type is required")
        
        # Convert string to enum
        try:
            violation_type = ViolationType[violation_type_str]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid violation_type: {violation_type_str}. Must be one of: {[v.name for v in ViolationType]}"
            )
        
        # Record violation (Awaited)
        warning_manager = WarningManager(db)
        result = await warning_manager.record_violation(
            interview_id=interview_id,
            violation_type=violation_type,
            metadata=metadata
        )
        
        # Check if error (duplicate or completed interview)
        if "error" in result:
            return result
        
        # Send Email if Terminated
        if result.get("should_terminate"):
            try:
                # Fetch details for email (Awaited)
                interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
                if interview:
                    resume = await db.resumes.find_one({"_id": ObjectId(interview["resume_id"])})
                    if resume and resume.get("email"):
                        # Send email in background
                        from services.email.email_service import send_cheating_disqualification_email
                        
                        background_tasks.add_task(
                            send_cheating_disqualification_email,
                            to_email=resume["email"],
                            candidate_name=resume.get("candidate_name", "Candidate"),
                            reason=result.get("termination_reason", "Violation limit exceeded"),
                            db=db
                        )
                        logger.info(f"📧 Disqualification email queued for {resume['email']}")
            except Exception as e:
                logger.error(f"Failed to queue disqualification email: {e}")
                
            # Queue background task to evaluate any pending/un-evaluated answers
            background_tasks.add_task(
                evaluate_terminated_interview_background,
                interview_id,
                db
            )

        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to record violation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{interview_id}")
@limiter.limit("60/minute")
async def get_violations(
    request: Request,
    interview_id: str,
    db = Depends(get_db)
):
    """
    Get violation history for an interview
    
    Response:
    {
        "violations": [
            {
                "type": "TAB_SWITCHED",
                "severity": 2,
                "strikes": 0,  # Grace applied
                "timestamp": "2026-01-16T12:00:00Z",
                "metadata": {},
                "grace_applied": true,
                "message": {...}
            }
        ],
        "total_strikes": 0,
        "first_violation_at": "2026-01-16T12:00:00Z",
        "last_violation_at": "2026-01-16T12:00:00Z"
    }
    """
    
    try:
        warning_manager = WarningManager(db)
        violations = await warning_manager.get_violation_history(interview_id)
        
        # Get interview for metadata (Awaited)
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        return {
            "violations": violations,
            "total_strikes": interview.get("total_strikes", 0),
            "first_violation_at": interview.get("first_violation_at"),
            "last_violation_at": interview.get("last_violation_at")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get violations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{interview_id}/summary")
@limiter.limit("60/minute")
async def get_violation_summary(
    request: Request,
    interview_id: str,
    db = Depends(get_db)
):
    """
    Get violation summary for dashboard
    
    Response:
    {
        "total_violations": 3,
        "total_strikes": 2,
        "max_strikes": 3,
        "strikes_remaining": 1,
        "severity_breakdown": {
            "info": 0,
            "warning": 2,
            "critical": 1,
            "terminal": 0
        },
        "is_terminated": false,
        "first_violation_at": "2026-01-16T12:00:00Z",
        "last_violation_at": "2026-01-16T12:05:00Z"
    }
    """
    
    try:
        warning_manager = WarningManager(db)
        summary = await warning_manager.get_strike_summary(interview_id)
        
        if "error" in summary:
            raise HTTPException(status_code=404, detail=summary["error"])
        
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get violation summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
