from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from bson import ObjectId
from fastapi import HTTPException
from core.constants import (
    InterviewState, 
    DEFAULT_INTERVIEW_Duration_MINUTES, 
    DEFAULT_QUESTION_DURATION_SECONDS,
    GRACE_PERIOD_SECONDS
)
from utils.db_helpers import get_document_or_404_async
from utils.logger import logger

class InterviewOrchestrator:
    """
    The Central Nervous System of the Interview Process (Async).
    Enforces the Finite State Machine (FSM) and Time Limits.
    """

    def __init__(self, db):
        self.db = db

    def get_utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def _get_interview(self, interview_id: str) -> Dict[str, Any]:
        """Fetch interview with robust error handling (Async)"""
        return await get_document_or_404_async(self.db.interviews, interview_id)

    async def _update_state(self, interview_id: str, new_state: InterviewState, updates: Dict[str, Any] = None):
        """Atomic state transition helper (Async)"""
        if updates is None:
            updates = {}
        
        updates["state"] = new_state.value
        updates["updated_at"] = self.get_utc_now().isoformat()
        
        # Sync legacy 'status' field for backward compatibility
        if new_state == InterviewState.COMPLETED:
            updates["status"] = "completed"
            updates["is_completed"] = True
        elif new_state == InterviewState.TERMINATED:
            updates["status"] = "terminated"
        
        await self.db.interviews.update_one(
            {"_id": ObjectId(interview_id)},
            {"$set": updates}
        )

    async def start_session(self, interview_id: str) -> Dict[str, Any]:
        """
        Transition: INIT -> QUESTION_ACTIVE (0)
        Sets the global interview timer (Async).
        """
        interview = await self._get_interview(interview_id)
        current_state = interview.get("state", InterviewState.CREATED.value)
        
        # Idempotency: If already started, just return current state
        if current_state != InterviewState.CREATED.value:
            return await self.get_state_snapshot(interview_id)

        now = self.get_utc_now()
        duration_minutes = DEFAULT_INTERVIEW_Duration_MINUTES
        
        expires_at = now + timedelta(minutes=duration_minutes)
        
        # Determine first question duration
        q_limit = self._get_time_limit_for_question(interview, 0)
        phase_expires_at = now + timedelta(seconds=q_limit)

        updates = {
            "started_at": now.isoformat(),
            "interview_expires_at": expires_at.isoformat(),
            "question_started_at": now.isoformat(),
            "question_duration": q_limit,
            "question_expires_at": phase_expires_at.isoformat(),
            "current_question_index": 0,
        }
        
        await self._update_state(interview_id, InterviewState.QUESTION_ACTIVE, updates)
        return await self.get_state_snapshot(interview_id)

    async def get_state_snapshot(self, interview_id: str) -> Dict[str, Any]:
        """
        Resume-Safe: Calculates 'time_remaining' dynamically based on server clock (Async).
        """
        interview = await self._get_interview(interview_id)
        now = self.get_utc_now()
        
        state = interview.get("state", InterviewState.CREATED.value)
        idx = interview.get("current_question_index", 0)
        
        # 1. Global Time Check
        global_expires = interview.get("interview_expires_at")
        global_remaining = 0
        if global_expires:
            exp_dt = datetime.fromisoformat(global_expires.replace("Z", "+00:00"))
            global_remaining = max(0, (exp_dt - now).total_seconds())

        # 2. Phase Time Check
        phase_expires = interview.get("question_expires_at")
        phase_remaining = 0
        if phase_expires:
            p_exp_dt = datetime.fromisoformat(phase_expires.replace("Z", "+00:00"))
            phase_remaining = max(0, (p_exp_dt - now).total_seconds())
        
        # Get current question content
        questions = interview.get("questions", [])
        current_q = None
        current_q_content = None
        if questions and idx < len(questions):
            current_q = questions[idx] 
            if isinstance(current_q, dict) and "question" in current_q:
                 current_q_content = current_q["question"]
            else:
                 current_q_content = current_q
        
        q_limit = self._get_time_limit_for_question(interview, idx)
        
        return {
            "interview_id": str(interview["_id"]),
            "state": state,
            "current_question_index": idx,
            "total_questions": len(questions),
            "current_question": current_q_content,
            "time_remaining_global": global_remaining,
            "time_remaining_question": phase_remaining,
            "time_limit_question": q_limit,
            "question_expires_at": phase_expires,
            "is_completed": state == InterviewState.COMPLETED.value
        }

    async def validate_submission(self, interview_id: str, client_idx: int) -> bool:
        """
        Validate if submission is allowed (Time + Sequence) (Async).
        """
        interview = await self._get_interview(interview_id)
        state = interview.get("state")
        server_idx = interview.get("current_question_index", 0)
        
        if client_idx != server_idx:
            logger.warning(f"Sequence Mismatch: Client {client_idx} vs Server {server_idx}")
            if client_idx < server_idx:
                return False
            raise HTTPException(400, "Invalid question index sequence")

        now = self.get_utc_now()
        phase_expires = interview.get("question_expires_at")
        
        if phase_expires:
            p_exp_dt = datetime.fromisoformat(phase_expires.replace("Z", "+00:00"))
            if now > (p_exp_dt + timedelta(seconds=GRACE_PERIOD_SECONDS)):
                raise ValueError("Time limit exceeded") 

        return True

    def _get_time_limit_for_question(self, interview: Dict[str, Any], question_index: int) -> int:
        """Determines the time limit for a specific question (remains sync as it works on dict)"""
        questions = interview.get("questions", [])
        if not questions or question_index >= len(questions):
            return DEFAULT_QUESTION_DURATION_SECONDS
            
        q_obj = questions[question_index]
        
        if isinstance(q_obj, dict) and "time_limit" in q_obj:
            return int(q_obj["time_limit"])
            
        if isinstance(q_obj, dict) and "section_index" in q_obj:
            sections = interview.get("sections", [])
            sec_idx = q_obj["section_index"]
            if sections and 0 <= sec_idx < len(sections):
                return int(sections[sec_idx].get("time_per_question", DEFAULT_QUESTION_DURATION_SECONDS))
        
        if isinstance(q_obj, dict) and "type" in q_obj:
            q_type = q_obj["type"]
            if q_type == "MCQ": return 60
            if q_type == "Code": return 600
        
        return int(interview.get("question_time_limit_seconds", DEFAULT_QUESTION_DURATION_SECONDS))

    async def transition_next(self, interview_id: str):
        """
        Move to next question or complete (Async).
        """
        interview = await self._get_interview(interview_id)
        current_idx = interview.get("current_question_index", 0)
        questions = interview.get("questions", [])
        
        next_idx = current_idx + 1
        
        if next_idx >= len(questions):
            await self._update_state(interview_id, InterviewState.COMPLETED, {
                "completed_at": self.get_utc_now().isoformat(),
                "question_expires_at": None
            })
        else:
            q_limit = self._get_time_limit_for_question(interview, next_idx)
            now = self.get_utc_now()
            phase_expires_at = now + timedelta(seconds=q_limit)
            
            await self._update_state(interview_id, InterviewState.QUESTION_ACTIVE, {
                "current_question_index": next_idx,
                "question_started_at": now.isoformat(),
                "question_duration": q_limit,
                "question_expires_at": phase_expires_at.isoformat()
            })
