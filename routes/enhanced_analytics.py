"""
Enhanced Analytics API Routes (Async)
Endpoints for comprehensive interview analytics
"""
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from utils import get_db
from utils.validators import validate_object_id
from utils.authorization import verify_interview_access
from core.auth import get_current_user
from services.analytics.enhanced_analytics import InterviewAnalytics

router = APIRouter()

@router.get("/interviews/{interview_id}/enhanced-analytics")
async def get_enhanced_analytics(
    interview_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    Get comprehensive interview analytics with warning breakdown (Async)
    """
    try:
        # Validate and authorize (verify_interview_access needs to be awaited if async)
        interview_obj_id = validate_object_id(interview_id, "Interview ID")
        
        # Checking if verify_interview_access is async
        from utils.authorization import verify_interview_access
        # According to task.md, authorization helpers were migrated to async
        await verify_interview_access(db, interview_obj_id, current_user.id, is_recruiter=True)
        
        # Generate analytics (Async Engine)
        analytics_engine = InterviewAnalytics(interview_id, db)
        await analytics_engine.initialize()
        analytics_data = await analytics_engine.generate_complete_analytics()
        
        return {
            "success": True,
            "interview_id": interview_id,
            "analytics": analytics_data
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate analytics: {str(e)}")


@router.get("/interviews/{interview_id}/warning-breakdown")
async def get_warning_breakdown(
    interview_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get detailed warning type breakdown (Async)"""
    try:
        interview_obj_id = validate_object_id(interview_id, "Interview ID")
        await verify_interview_access(db, interview_obj_id, current_user.id, is_recruiter=True)
        
        analytics_engine = InterviewAnalytics(interview_id, db)
        await analytics_engine.initialize()
        integrity_metrics = await analytics_engine.analyze_integrity()
        
        return {
            "success": True,
            "warning_breakdown": integrity_metrics
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
