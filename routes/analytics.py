"""
Analytics Routes (Async)
Provides analytics and statistics for recruiters
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from typing import Optional
from utils import get_db
from core.auth import get_current_user
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

from services.analytics.analytics import (
    get_analytics_summary as service_get_summary,
    get_analytics_trends as service_get_trends,
)

@router.get("/summary")
async def get_analytics_summary(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get comprehensive analytics summary for recruiter (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Only recruiters can access analytics")
    
    try:
        # Call consolidated service function (now async)
        result = await service_get_summary(current_user.id, db)
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"Failed to generate analytics summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate analytics")


@router.get("/trends")
async def get_analytics_trends(
    days: int = Query(7, ge=1, le=90),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get application trends over specified time period (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Only recruiters can access analytics")
    
    try:
        # Call consolidated service function (now async)
        result = await service_get_trends(current_user.id, days, db)
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"Failed to generate analytics trends: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate trends")


@router.get("/recruiter/{recruiter_id}")
async def get_recruiter_analytics(
    recruiter_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get comprehensive analytics for a recruiter (Async)"""
    # Verify access
    if str(current_user.id) != recruiter_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        # We reuse the summary logic but could add more recruiter-specific flags if needed
        result = await service_get_summary(recruiter_id, db)
        
        # Add additional recruiter specific detail: Recent Interviews
        interviews = await db.interviews.find({"recruiter_id": recruiter_id}).sort("created_at", -1).limit(10).to_list(length=10)
        
        recent_interviews = []
        for i in interviews:
            resume = await db.resumes.find_one({"_id": ObjectId(i.get("resume_id"))})
            recent_interviews.append({
                "interview_id": str(i["_id"]),
                "candidate_name": resume.get("candidate_name", "Unknown") if resume else "Unknown",
                "status": i.get("status", "pending"),
                "final_score": i.get("final_score"),
                "created_at": i.get("created_at"),
                "completed_at": i.get("completed_at")
            })
            
        return {
            **result["kpis"],
            "score_distribution": result.get("status_distribution", {}), # Mapping status to dist for simplicity or using result.status_distribution
            "recent_interviews": recent_interviews,
            "avg_score": result.get("average_match_score", 0)
        }
    except Exception as e:
        logger.error(f"Failed to generate recruiter analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate analytics")


@router.get("/system")
async def get_system_analytics(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get system-wide analytics (admin only, Async)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Parallel counts (Async)
        import asyncio
        users_task = db.users.count_documents({})
        recruiters_task = db.users.count_documents({"role": "recruiter"})
        jobs_task = db.jds.count_documents({})
        apps_task = db.resumes.count_documents({})
        interviews_task = db.interviews.count_documents({})
        
        results = await asyncio.gather(users_task, recruiters_task, jobs_task, apps_task, interviews_task)
        
        return {
            "total_users": results[0],
            "total_recruiters": results[1],
            "total_jobs": results[2],
            "total_applications": results[3],
            "total_interviews": results[4]
        }
    except Exception as e:
        logger.error(f"Failed to generate system analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate system analytics")
