"""
Warning Management System for Interview Proctoring (Async)
Handles violation severity classification, strike calculation, and termination logic
"""

from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class ViolationSeverity(Enum):
    INFO = 1
    WARNING = 2
    CRITICAL = 3
    TERMINAL = 4

class ViolationType(Enum):

    AUDIO_DETECTED = "AUDIO_DETECTED"
    TAB_SWITCHED = "TAB_SWITCHED"
    WINDOW_BLUR = "WINDOW_BLUR"
    WINDOW_FOCUS_LOST = "WINDOW_FOCUS_LOST"
    COPY_ATTEMPTED = "COPY_ATTEMPTED"
    PASTE_ATTEMPTED = "PASTE_ATTEMPTED"
    CUT_ATTEMPTED = "CUT_ATTEMPTED"
    KEYBOARD_SHORTCUT_BLOCKED = "KEYBOARD_SHORTCUT_BLOCKED"
    FULLSCREEN_EXIT = "FULLSCREEN_EXIT"
    FULLSCREEN_REQUIRED = "FULLSCREEN_REQUIRED"   # FIX #5: was missing, caused 400 → retry loop
    CONNECTION_LOST = "CONNECTION_LOST"
    SLOW_CONNECTION = "SLOW_CONNECTION"
    DEVTOOLS_ATTEMPTED = "DEVTOOLS_ATTEMPTED"
    VIEW_SOURCE_ATTEMPTED = "VIEW_SOURCE_ATTEMPTED"
    RIGHT_CLICK_BLOCKED = "RIGHT_CLICK_BLOCKED"
    FOCUS_WARNING = "FOCUS_WARNING"
    # Vision-based (client-side face-api.js detection)
    NO_PERSON = "NO_PERSON"
    MULTIPLE_FACES = "MULTIPLE_FACES"

class WarningManager:
    """Production-grade warning management system (Async)"""
    
    SEVERITY_MAP = {
        ViolationType.CONNECTION_LOST: ViolationSeverity.WARNING,
        ViolationType.TAB_SWITCHED: ViolationSeverity.WARNING,
        ViolationType.WINDOW_BLUR: ViolationSeverity.WARNING,
        ViolationType.WINDOW_FOCUS_LOST: ViolationSeverity.WARNING,
        ViolationType.AUDIO_DETECTED: ViolationSeverity.WARNING,
        ViolationType.DEVTOOLS_ATTEMPTED: ViolationSeverity.CRITICAL,
        ViolationType.VIEW_SOURCE_ATTEMPTED: ViolationSeverity.CRITICAL,
        ViolationType.RIGHT_CLICK_BLOCKED: ViolationSeverity.WARNING,
        ViolationType.FOCUS_WARNING: ViolationSeverity.INFO,
        ViolationType.FULLSCREEN_REQUIRED: ViolationSeverity.INFO,  # FIX #5: browser permission ≠ cheating (0 strikes)
        # Vision-based violations (1 strike each)
        ViolationType.NO_PERSON: ViolationSeverity.WARNING,
        ViolationType.MULTIPLE_FACES: ViolationSeverity.WARNING,
    }
    
    STRIKE_VALUES = {
        ViolationSeverity.INFO: 0, ViolationSeverity.WARNING: 1,
        ViolationSeverity.CRITICAL: 2, ViolationSeverity.TERMINAL: 999
    }
    
    MAX_STRIKES = 3
    DEDUPLICATION_WINDOW = 5  # seconds — cooling period between identical violations
    
    def __init__(self, db):
        self.db = db

    async def record_violation(self, interview_id: str, violation_type: ViolationType, metadata: Dict = None) -> Dict:
        """Asynchronous violation recorder — atomic, race-condition-free"""
        return await self._process_violation(interview_id, violation_type, metadata)

    def record_violation_sync(self, interview_id: str, violation_type: ViolationType, metadata: Dict = None) -> Dict:
        """Synchronous version — kept for API compatibility, should not be called in async context"""
        raise NotImplementedError("Use async record_violation() in an async context.")

    async def _process_violation(self, interview_id: str, violation_type: ViolationType, metadata: Dict = None, **_kwargs) -> Dict:
        """
        FIX #1 (CRITICAL) — Atomic find_one_and_update eliminates the race condition.

        PREVIOUS BUG: Non-atomic read-then-write:
          1. Read total_strikes=0 from DB
          2. Compute new_strike_total = 0 + 1 = 1 locally
          3. Decide should_terminate = (1 >= 3) = False ← looks correct
          4. Write $inc to DB

        WHAT ACTUALLY HAPPENED with 3 concurrent requests:
          - All 3 read total_strikes=0 at the same time (before any write committed)
          - All 3 computed new_strike_total=1 and decided should_terminate=False
          - All 3 wrote $inc:{total_strikes: 1} → DB ended up at total_strikes=3
          - Next fetchInterview() saw proctoring_warning_count=3 and terminated

        FIX: The deduplication filter is embedded IN the MongoDB query.
        Only ONE concurrent request can satisfy the filter and increment the counter.
        All others return None (no-op). Counter is read from the UPDATED document.
        """
        severity = self.SEVERITY_MAP.get(violation_type, ViolationSeverity.WARNING)
        strikes = self.STRIKE_VALUES.get(severity, 1)

        now = datetime.now(timezone.utc)
        # FIX #6: timezone-aware dedup cutoff (was causing naive/aware TypeError suppressed by except)
        dedup_cutoff = (now - timedelta(seconds=self.DEDUPLICATION_WINDOW)).isoformat()

        violation_record = {
            "type": violation_type.value,
            "severity": severity.value,
            "strikes": strikes,
            "timestamp": now.isoformat(),
            "metadata": metadata or {},
            "grace_applied": False
        }

        # SINGLE ATOMIC OPERATION — dedup + increment + push all in one query
        # If same violation type was recorded within DEDUPLICATION_WINDOW seconds,
        # the $elemMatch filter will match → update is skipped → returns None
        updated_interview = await self.db.interviews.find_one_and_update(
            {
                "_id": ObjectId(interview_id),
                "is_completed": {"$ne": True},
                # MongoDB-level dedup: prevents concurrent duplicate writes
                "proctoring_violations": {
                    "$not": {
                        "$elemMatch": {
                            "type": violation_type.value,
                            "timestamp": {"$gte": dedup_cutoff}
                        }
                    }
                }
            },
            {
                "$push": {"proctoring_violations": violation_record},
                "$inc": {
                    "total_strikes": strikes,
                    "proctoring_warning_count": strikes
                },
                "$set": {"last_violation_at": now.isoformat()},
                "$setOnInsert": {"first_violation_at": now.isoformat()}
            },
            return_document=True  # Returns UPDATED document — total_strikes already incremented
        )

        if updated_interview is None:
            # Distinguish reason for no-op
            interview_check = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
            if not interview_check:
                logger.error(f"Interview {interview_id} not found during violation recording")
                return {"error": "Interview not found"}
            if interview_check.get("is_completed"):
                return {"error": "Interview already completed"}
            # Dedup suppressed this — normal & expected
            logger.info(f"[VIOLATION_DEDUP] {violation_type.value} suppressed for {interview_id} (within {self.DEDUPLICATION_WINDOW}s window)")
            return {"error": "Duplicate ignored"}

        # Read counter from the UPDATED document — no race possible
        new_strike_total = updated_interview.get("total_strikes", 0)
        should_terminate = severity == ViolationSeverity.TERMINAL or new_strike_total >= self.MAX_STRIKES

        logger.info(f"[VIOLATION_RECORDED] {violation_type.value} for interview {interview_id}")
        logger.info(f"Severity: {severity.name} | Strikes: +{strikes} → Total: {new_strike_total}/{self.MAX_STRIKES}")

        termination_reason = None
        if should_terminate:
            termination_reason = (
                f"Terminated due to {violation_type.value} violation."
                if severity == ViolationSeverity.TERMINAL
                else f"Max strikes exceeded ({new_strike_total}/{self.MAX_STRIKES})."
            )
            await self.db.interviews.update_one(
                {"_id": ObjectId(interview_id)},
                {"$set": {
                    "status": "terminated",
                    "is_completed": True,
                    "termination_reason": termination_reason,
                    "terminated_at": now.isoformat()
                }}
            )
            await self._sync_termination_to_application_async(interview_id, termination_reason)

        return {
            "success": True,
            "total_strikes": new_strike_total,
            "should_terminate": should_terminate,
            "termination_reason": termination_reason,
            "violation": violation_record,
            "strikes_remaining": max(0, self.MAX_STRIKES - new_strike_total),
            "grace_applied": False
        }

    async def get_violation_history(self, interview_id: str) -> List[Dict]:
        """Fetch violation history for an interview (Async)"""
        interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)}, {"proctoring_violations": 1})
        if not interview: return []
        return interview.get("proctoring_violations", [])

    async def get_strike_summary(self, interview_id: str) -> Dict:
        """Fetch strike summary for an interview (Async)"""
        interview = await self.db.interviews.find_one(
            {"_id": ObjectId(interview_id)},
            {"total_strikes": 1, "proctoring_violations": 1, "status": 1, "first_violation_at": 1, "last_violation_at": 1}
        )
        if not interview: return {"error": "Interview not found"}
        
        violations = interview.get("proctoring_violations", [])
        severity_counts = {"info": 0, "warning": 0, "critical": 0, "terminal": 0}
        
        for v in violations:
            sev = v.get("severity", 1)
            if sev == 1: severity_counts["info"] += 1
            elif sev == 2: severity_counts["warning"] += 1
            elif sev == 3: severity_counts["critical"] += 1
            elif sev == 4: severity_counts["terminal"] += 1
            
        total_strikes = interview.get("total_strikes", 0)
        return {
            "total_violations": len(violations),
            "total_strikes": total_strikes,
            "max_strikes": self.MAX_STRIKES,
            "strikes_remaining": max(0, self.MAX_STRIKES - total_strikes),
            "severity_breakdown": severity_counts,
            "is_terminated": interview.get("status") == "terminated",
            "first_violation_at": interview.get("first_violation_at"),
            "last_violation_at": interview.get("last_violation_at")
        }

    async def _sync_termination_to_application_async(self, interview_id: str, reason: str):
        interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview: return
        app_query = {"job_id": interview.get("jd_id"), "resume_id": interview.get("resume_id")}
        await self.db.applications.update_one(app_query, {"$set": {"interview_status": "terminated", "cheater": True, "termination_reason": reason}})

    def _sync_termination_to_application_sync(self, interview_id: str, reason: str):
        """Legacy sync method — backward compatibility only"""
        interview = self.db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview: return
        app_query = {"job_id": interview.get("jd_id"), "resume_id": interview.get("resume_id")}
        self.db.applications.update_one(app_query, {"$set": {"interview_status": "terminated", "cheater": True, "termination_reason": reason}})
