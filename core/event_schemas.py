from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

class BaseEvent(BaseModel):
    """Base class for all system events"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    type: str

class InterviewStartedEvent(BaseEvent):
    type: str = "INTERVIEW_STARTED"
    interview_id: str
    user_id: str

class InterviewCompletedEvent(BaseEvent):
    type: str = "INTERVIEW_COMPLETED"
    interview_id: str
    user_id: str
    score: float
    status: str

class ReclaimRequestedEvent(BaseEvent):
    type: str = "RECLAIM_REQUESTED"
    interview_id: str
    candidate_id: str
    recruiter_id: str
    reason: str

class ReclaimApprovedEvent(BaseEvent):
    type: str = "RECLAIM_APPROVED"
    interview_id: str
    candidate_id: str
    recruiter_id: str

class ViolationDetectedEvent(BaseEvent):
    type: str = "VIOLATION_DETECTED"
    interview_id: str
    violation_type: str
    confidence: float
    timestamp_frame: str
