"""
Interview Timer Service - Server-Authoritative Timing
Prevents client-side drift and ensures accurate timeout detection
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class InterviewTimer:
    """Production-grade server-authoritative timer"""
    
    # Configuration
    QUESTION_DURATION_SECONDS = 60  # 1 minute per question
    GRACE_PERIOD_SECONDS = 5        # 5 second grace for network latency
    MAX_PAUSE_DURATION = 300        # 5 minutes max pause
    
    def __init__(self, db):
        self.db = db
    
    async def start_timer(self, interview_id: str) -> Dict:
        """
        Start question timer with absolute expiration timestamp
        
        Args:
            interview_id: Interview ID
        
        Returns:
            Dict with started_at, expires_at, duration, grace_period
        """
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.QUESTION_DURATION_SECONDS)
        
        # Update database
        result = await self.db.interviews.update_one(
            {"_id": ObjectId(interview_id)},
            {
                "$set": {
                    "question_started_at": now.isoformat(),
                    "question_expires_at": expires_at.isoformat(),
                    "timer_state": "active"
                }
            }
        )
        
        if result.modified_count == 0:
            logger.warning(f"Timer start failed for interview {interview_id}")
            raise ValueError("Failed to start timer")
        
        logger.info(
            f"Timer started for interview {interview_id}: "
            f"{self.QUESTION_DURATION_SECONDS}s duration, "
            f"expires at {expires_at.isoformat()}"
        )
        
        return {
            "started_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "duration_seconds": self.QUESTION_DURATION_SECONDS,
            "grace_period_seconds": self.GRACE_PERIOD_SECONDS
        }
    
    async def check_timeout(self, interview_id: str) -> Dict:
        """
        Check if timer has expired (with grace period)
        
        Args:
            interview_id: Interview ID
        
        Returns:
            Dict with timed_out, seconds_remaining, grace_period_active
        """
        
        interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
        
        if not interview:
            return {"error": "Interview not found"}
        
        if not interview.get("question_expires_at"):
            return {"error": "No active timer"}
        
        # Parse expiration time
        expires_at = datetime.fromisoformat(interview["question_expires_at"])
        now = datetime.now(timezone.utc)
        
        # Calculate grace expiration (expires_at + grace period)
        grace_expires_at = expires_at + timedelta(seconds=self.GRACE_PERIOD_SECONDS)
        
        # Check if timed out (beyond grace period)
        timed_out = now > grace_expires_at
        
        # Calculate remaining time (can be negative)
        seconds_remaining = max(0, int((expires_at - now).total_seconds()))
        
        # Check if in grace period
        grace_period_active = expires_at < now < grace_expires_at
        
        return {
            "timed_out": timed_out,
            "seconds_remaining": seconds_remaining,
            "grace_period_active": grace_period_active,
            "expires_at": expires_at.isoformat(),
            "grace_expires_at": grace_expires_at.isoformat()
        }
    
    async def pause_timer(self, interview_id: str, reason: str) -> Dict:
        """
        Pause timer (for technical issues)
        
        Args:
            interview_id: Interview ID
            reason: Reason for pause (e.g., "camera_failure", "network_issue")
        
        Returns:
            Dict with success, paused_at, remaining_seconds
        """
        
        interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
        
        if not interview:
            return {"success": False, "error": "Interview not found"}
        
        if interview.get("timer_state") != "active":
            return {"success": False, "error": "Timer not active"}
        
        # Calculate remaining time
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromisoformat(interview["question_expires_at"])
        remaining_seconds = max(0, int((expires_at - now).total_seconds()))
        
        # Update database
        result = await self.db.interviews.update_one(
            {"_id": ObjectId(interview_id)},
            {
                "$set": {
                    "timer_paused_at": now.isoformat(),
                    "timer_remaining_seconds": remaining_seconds,
                    "timer_state": "paused",
                    "pause_reason": reason
                }
            }
        )
        
        if result.modified_count == 0:
            return {"success": False, "error": "Failed to pause timer"}
        
        logger.info(
            f"Timer paused for interview {interview_id}: "
            f"reason={reason}, remaining={remaining_seconds}s"
        )
        
        return {
            "success": True,
            "paused_at": now.isoformat(),
            "remaining_seconds": remaining_seconds,
            "reason": reason
        }
    
    async def resume_timer(self, interview_id: str) -> Dict:
        """
        Resume paused timer
        
        Args:
            interview_id: Interview ID
        
        Returns:
            Dict with success, resumed_at, expires_at
        """
        
        interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
        
        if not interview:
            return {"success": False, "error": "Interview not found"}
        
        if interview.get("timer_state") != "paused":
            return {"success": False, "error": "Timer not paused"}
        
        # Check if pause duration exceeded max
        paused_at = datetime.fromisoformat(interview["timer_paused_at"])
        now = datetime.now(timezone.utc)
        pause_duration = int((now - paused_at).total_seconds())
        
        if pause_duration > self.MAX_PAUSE_DURATION:
            logger.error(
                f"Pause duration exceeded maximum for interview {interview_id}: "
                f"{pause_duration}s > {self.MAX_PAUSE_DURATION}s"
            )
            return {
                "success": False,
                "error": f"Pause duration exceeded maximum ({self.MAX_PAUSE_DURATION}s)"
            }
        
        # Calculate new expiration time
        remaining_seconds = interview["timer_remaining_seconds"]
        new_expires_at = now + timedelta(seconds=remaining_seconds)
        
        # Update database
        result = await self.db.interviews.update_one(
            {"_id": ObjectId(interview_id)},
            {
                "$set": {
                    "question_expires_at": new_expires_at.isoformat(),
                    "timer_resumed_at": now.isoformat(),
                    "timer_state": "active"
                },
                "$unset": {
                    "timer_paused_at": "",
                    "timer_remaining_seconds": "",
                    "pause_reason": ""
                }
            }
        )
        
        if result.modified_count == 0:
            return {"success": False, "error": "Failed to resume timer"}
        
        logger.info(
            f"Timer resumed for interview {interview_id}: "
            f"pause_duration={pause_duration}s, new_expires_at={new_expires_at.isoformat()}"
        )
        
        return {
            "success": True,
            "resumed_at": now.isoformat(),
            "expires_at": new_expires_at.isoformat(),
            "pause_duration_seconds": pause_duration
        }
    
    async def get_remaining_time(self, interview_id: str) -> int:
        """
        Get remaining time in seconds
        
        Args:
            interview_id: Interview ID
        
        Returns:
            Remaining seconds (0 if expired)
        """
        
        timeout_check = await self.check_timeout(interview_id)
        
        if "error" in timeout_check:
            return 0
        
        return timeout_check["seconds_remaining"]

    async def process_question_timeouts(self, socket_controller=None):
        """Find active questions that have expired and force timeout."""
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            expired_interviews = await self.db.interviews.find({
                "state": "QUESTION_ACTIVE",
                "question_expires_at": {"$lte": now}
            }).to_list(length=100)
            
            for interview in expired_interviews:
                interview_id = str(interview["_id"])
                logger.info(f"Auto-timing out interview {interview_id} at {now}")
                
                # Submit empty answer
                from services.interview.core import submit_response_fast, InterviewResponse
                try:
                    result = await submit_response_fast(interview_id, InterviewResponse(response="", timeout=True), self.db)
                    
                    # Emit to socket if connected
                    if socket_controller:
                        for sid, session in socket_controller.session_manager.active_sessions.items():
                            if session.get("interview_id") == interview_id:
                                await socket_controller.socketio.emit('next_question', {
                                    'status': 'advanced',
                                    'question_index': result.get('response', {}).get('next_idx', 0),
                                    'completed': result.get('response', {}).get('status') == 'completed'
                                }, to=sid)
                except Exception as e:
                    logger.error(f"Failed to auto-timeout interview {interview_id}: {e}")
        except Exception as e:
            logger.error(f"Error checking for timeouts: {e}")
