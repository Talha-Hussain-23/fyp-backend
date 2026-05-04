"""
Admin Monitoring Routes (Async)
Endpoints for system health checks and consistency monitoring
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from utils import get_db, logger
from core.auth import get_current_user
from app.proctoring.proctoring_heartbeat import ProctoringHeartbeat

router = APIRouter()

@router.get("/health")
async def system_health(db = Depends(get_db)):
    """Comprehensive system health check (Async)"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {}
        }
        
        # Check database connectivity
        try:
            await db.command('ping')
            health_status["components"]["database"] = {"status": "healthy", "message": "MongoDB active"}
        except Exception as e:
            health_status["components"]["database"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Check collections
        collections = ["users", "jds", "applications", "interviews", "resumes"]
        existing = await db.list_collection_names()
        missing = [c for c in collections if c not in existing]
        
        health_status["components"]["collections"] = {
            "status": "healthy" if not missing else "warning",
            "missing": missing
        }
        
        # Recent activity
        try:
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            recent_apps = await db.applications.count_documents({"applied_at": {"$gte": week_ago}})
            health_status["components"]["activity"] = {"status": "healthy", "recent_apps_7d": recent_apps}
        except: pass
        
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "error", "error": str(e)}

@router.get("/consistency-check")
async def consistency_check(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Check data consistency across collections (Async)"""
    if not current_user.is_recruiter and current_user.role != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        issues = []
        stats = {}
        
        # 1. Completed interviews missing score_breakdown (more comprehensive than just 'score')
        interviews_no_score = await db.interviews.find({
            "is_completed": True,
            "score_breakdown": {"$exists": False}
        }).limit(100).to_list(length=100)
        
        if interviews_no_score:
            issues.append({
                "severity": "HIGH", "category": "missing_breakdown", "count": len(interviews_no_score),
                "message": f"{len(interviews_no_score)} interviews missing breakdown",
                "sample_ids": [str(i["_id"]) for i in interviews_no_score[:5]]
            })
        stats["interviews_without_breakdown"] = len(interviews_no_score)
        
        # 2. Orphaned sessions
        orphaned = []
        sessions = await db.proctoring_sessions.find().limit(100).to_list(length=100)
        for s in sessions:
            iid = s.get("interview_id")
            if iid:
                exists = await db.interviews.find_one({"_id": ObjectId(iid)})
                if not exists: orphaned.append(str(s.get("session_id")))
        
        if orphaned:
            issues.append({"severity": "MEDIUM", "category": "orphaned_sessions", "count": len(orphaned), "samples": orphaned[:5]})
        stats["orphaned_sessions"] = len(orphaned)
        
        result = {
            "status": "consistent" if not issues else "inconsistent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_issues": len(issues),
            "issues": issues,
            "statistics": stats
        }
        await db.consistency_reports.insert_one(result)
        return result
    except Exception as e:
        logger.error(f"Consistency check failed: {e}")
        raise HTTPException(500, str(e))

@router.get("/proctoring/session/{session_id}/health")
async def proctoring_session_health(session_id: str, db = Depends(get_db)):
    heartbeat_service = ProctoringHeartbeat(db)
    return await heartbeat_service.check_session_health(session_id)

@router.get("/proctoring/session/{session_id}/summary")
async def proctoring_session_summary(session_id: str, db = Depends(get_db)):
    heartbeat_service = ProctoringHeartbeat(db)
    return await heartbeat_service.get_session_summary(session_id)

@router.get("/statistics")
async def system_statistics(current_user = Depends(get_current_user), db = Depends(get_db)):
    if not current_user.is_recruiter and current_user.role != "admin":
        raise HTTPException(403, "Admin access required")
    try:
        import asyncio
        users_task = db.users.count_documents({})
        jobs_task = db.jds.count_documents({"archived": {"$ne": True}})
        apps_task = db.applications.count_documents({})
        interviews_task = db.interviews.count_documents({})
        sessions_task = db.proctoring_sessions.count_documents({})
        
        counts = await asyncio.gather(users_task, jobs_task, apps_task, interviews_task, sessions_task)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collections": {
                "users": counts[0], "jobs": counts[1], "applications": counts[2], 
                "interviews": counts[3], "proctoring_sessions": counts[4]
            }
        }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(500, str(e))
