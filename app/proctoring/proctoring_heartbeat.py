"""
Proctoring Heartbeat Service (Async)
Monitors frame processing health and detects gaps/issues
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

class ProctoringHeartbeat:
    """Manages proctoring session health monitoring (Async)"""
    
    HEARTBEAT_INTERVAL = 30
    MAX_FRAME_GAP = 100
    MAX_TIME_GAP = 60
    
    def __init__(self, db):
        self.db = db
        self.session_metrics = {}

    def should_log_heartbeat(self, session_id: str, frame_number: int) -> bool:
        """
        Check if a heartbeat should be logged for this frame.
        We log every HEARTBEAT_INTERVAL frames to monitor health without flooding the DB.
        """
        # Always log the first frame
        if frame_number == 1:
            return True
            
        # Then every N frames
        return frame_number % self.HEARTBEAT_INTERVAL == 0

    async def log_heartbeat(self, session_id: str, interview_id: str, frame_number: int, person_count: int, processing_time_ms: float, has_violations: bool):
        """Log a heartbeat (Async)"""
        try:
            heartbeat_doc = {
                "session_id": session_id,
                "interview_id": interview_id,
                "frame_number": frame_number,
                "person_count": person_count,
                "processing_time_ms": processing_time_ms,
                "has_violations": has_violations,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "heartbeat"
            }
            
            await self.db.proctoring_heartbeats.insert_one(heartbeat_doc)
            self._update_local_metrics(session_id, frame_number, processing_time_ms)
            
        except Exception as e:
            logger.error(f"Failed to log heartbeat: {e}")

    def _update_local_metrics(self, session_id: str, frame_number: int, processing_time_ms: float):
        """Internal helper to update in-memory stats"""
        if session_id not in self.session_metrics:
            self.session_metrics[session_id] = {
                "last_heartbeat_frame": frame_number,
                "last_heartbeat_time": datetime.now(timezone.utc),
                "total_heartbeats": 0,
                "processing_times": []
            }
        
        metrics = self.session_metrics[session_id]
        metrics["last_heartbeat_frame"] = frame_number
        metrics["last_heartbeat_time"] = datetime.now(timezone.utc)
        metrics["total_heartbeats"] += 1
        metrics["processing_times"].append(processing_time_ms)
        
        if len(metrics["processing_times"]) > 10:
            metrics["processing_times"].pop(0)
        
        metrics["avg_processing_time"] = sum(metrics["processing_times"]) / len(metrics["processing_times"])

    async def check_session_health(self, session_id: str) -> Dict[str, Any]:
        """Get current health status of a session (Async)"""
        try:
            metrics = self.session_metrics.get(session_id, {})
            session = await self.db.proctoring_sessions.find_one({"session_id": session_id})
            
            if not session:
                return {"status": "NOT_FOUND"}
            
            started_at = datetime.fromisoformat(session.get("started_at", datetime.now(timezone.utc).isoformat()).replace('Z', '+00:00'))
            duration_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
            
            heartbeat_count = await self.db.proctoring_heartbeats.count_documents({"session_id": session_id})
            violation_count = await self.db.proctoring_violations.count_documents({"session_id": session_id})
            
            health = {
                "status": "HEALTHY",
                "session_id": session_id,
                "duration_seconds": duration_seconds,
                "heartbeat_count": heartbeat_count,
                "violation_count": violation_count,
                "avg_processing_time_ms": metrics.get("avg_processing_time", 0),
                "last_heartbeat_frame": metrics.get("last_heartbeat_frame", 0),
                "alerts": []
            }
            
            if metrics.get("last_heartbeat_time"):
                time_since_heartbeat = (datetime.now(timezone.utc) - metrics["last_heartbeat_time"]).total_seconds()
                if time_since_heartbeat > 120:
                    health["status"] = "STALE"
                    health["alerts"].append({"type": "STALE_SESSION", "severity": "HIGH", "message": f"No heartbeat for {time_since_heartbeat:.0f}s"})
            
            if metrics.get("avg_processing_time", 0) > 500:
                health["alerts"].append({"type": "SLOW_PROCESSING", "severity": "MEDIUM", "message": "High processing latency"})
            
            return health
        except Exception as e:
            logger.error(f"Error checking health: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get comprehensive summary of session health (Async)"""
        try:
            heartbeats = await self.db.proctoring_heartbeats.find({"session_id": session_id}).sort("frame_number", 1).to_list(length=1000)
            violations = await self.db.proctoring_violations.find({"session_id": session_id}).sort("frame_number", 1).to_list(length=1000)
            session = await self.db.proctoring_sessions.find_one({"session_id": session_id})
            
            if not session: return {"error": "Session not found"}
            
            ptimes = [h.get("processing_time_ms", 0) for h in heartbeats]
            return {
                "session_id": session_id,
                "interview_id": session.get("interview_id"),
                "status": session.get("status"),
                "total_heartbeats": len(heartbeats),
                "total_violations": len(violations),
                "processing_stats": {
                    "avg_ms": sum(ptimes) / len(ptimes) if ptimes else 0,
                    "min_ms": min(ptimes) if ptimes else 0,
                    "max_ms": max(ptimes) if ptimes else 0
                }
            }
        except Exception as e:
            logger.error(f"Error getting summary: {e}")
            return {"error": str(e)}

    def cleanup_session(self, session_id: str):
        """Cleanup local metrics when session ends"""
        if session_id in self.session_metrics:
            del self.session_metrics[session_id]
