from enum import Enum

class InterviewState(str, Enum):
    """
    Finite State Machine (FSM) states for the Interview Orchestration Engine.
    ORDER MATTERS for progression logic.
    """
    CREATED = "CREATED"
    STARTED = "STARTED"
    QUESTION_ACTIVE = "QUESTION_ACTIVE"
    QUESTION_TIMEOUT = "QUESTION_TIMEOUT"
    QUESTION_SUBMITTED = "QUESTION_SUBMITTED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"

class ProctoringState(str, Enum):
    """
    States for the real-time proctoring engine.
    """
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    LOCKED = "LOCKED"
    TERMINATED = "TERMINATED"

# Default constraints
DEFAULT_INTERVIEW_Duration_MINUTES = 45
DEFAULT_QUESTION_DURATION_SECONDS = 300  # 5 minutes
GRACE_PERIOD_SECONDS = 5  # Allow 5s network latency for submissions
