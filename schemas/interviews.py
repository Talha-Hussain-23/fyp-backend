"""
Interview Schemas
Models for interview questions, responses, and evaluation
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class Question(BaseModel):
    """Interview question model."""
    id: int
    question: str  # Renamed from text to match backend
    type: str = "Descriptive"  # Descriptive, MCQ, Code
    options: Optional[List[str]] = None
    code_template: Optional[str] = None
    section_index: Optional[int] = None # NEW: For sectioned interviews
    time_limit: Optional[int] = None    # NEW: Per-question timing

    class Config:
        populate_by_name = True
        # Allow 'text' to map to 'question' for legacy compat if needed
        # But backend uses 'question' primarily now.


class InterviewResponse(BaseModel):
    """Candidate response to a question."""
    response: str
    timeout: bool = False
    duration_seconds: Optional[int] = None


class EvaluationResult(BaseModel):
    """AI evaluation result."""
    score: float
    feedback: str
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None
    confidence: Optional[float] = None


class InterviewSession(BaseModel):
    """Interview session metadata."""
    id: str
    job_id: str
    candidate_id: str
    status: str  # scheduled, in-progress, completed, evaluated
    questions: List[Question]
    current_question_index: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    overall_score: Optional[float] = None
    final_score: Optional[float] = None
    score_breakdown: Optional[Dict[str, Any]] = None  # NEW: Structured Breakdown
    
    class Config:
        from_attributes = True
