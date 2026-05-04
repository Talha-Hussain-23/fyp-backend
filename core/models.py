"""
MongoDB Schema Definitions
MongoDB is schemaless, but these define the expected document structure
"""

from datetime import datetime, timezone
from bson import ObjectId

# Collection names
COLLECTIONS = {
    "users": "users",
    "jds": "jds",
    "resumes": "resumes",
    "interviews": "interviews",
    "notifications": "notifications",
    "files": "files",
    "applications": "applications",
    "audit_logs": "audit_logs",
    "analytics_snapshots": "analytics_snapshots",
    "api_logs": "api_logs",
    "google_oauth_tokens": "google_oauth_tokens",
    "scheduled_interviews": "scheduled_interviews",
    "emails_sent": "emails_sent"
}

# Helper for UTC ISO format with Z suffix (Explicit is better for JS compatibility)
def get_utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

# Schema helper functions for MongoDB documents

def create_user_document(name: str, email: str, hashed_password: str, is_recruiter: bool = False):
    """
    Create a user document with all required fields.
    
    Args:
        name: User's full name
        email: User's email address
        hashed_password: Bcrypt hashed password
        is_recruiter: Whether user is a recruiter (default: False)
        
    Returns:
        Dictionary representing a user document
    """
    return {
        "name": name,
        "email": email,
        "hashed_password": hashed_password,
        "is_recruiter": bool(is_recruiter),
        "role": "recruiter" if is_recruiter else "candidate",  # Explicit role field
        "is_active": True,  # For emergency account deactivation
        "is_verified": False,
        "verification_token": None,
        "verified_at": None,
        "password_reset_token": None,
        "password_reset_expires": None,
        "avatar_url": None,
        "organization": None,
        "settings": {
            "notifications": True,
            "theme": "light"
        },
        "token_version": 0,
        "created_at": get_utc_now()
    }

def create_jd_document(recruiter_id: str, description: str, difficulty_level: str = "Medium", 
                      num_questions: int = 5, apply_deadline: str = None, title: str = None,
                      num_vacancies: int = 1, question_type: str = "Descriptive", 
                      question_types: list = None,  # New: support multiple types
                      max_shortlist: int = 10, ai_instructions: str = None,
                      evaluation_config: dict = None, invite_rule: str = "Top 10", invite_rule_n: int = None,
                      embedding: list = None, interview_config: dict = None):
    """
    Create a job description document
    
    IMPORTANT: apply_deadline MUST be in UTC format!
    - Correct: "2025-11-20T12:00:00Z" (UTC time with 'Z' suffix)
    - Correct: "2025-11-20T17:00:00+05:00" (with timezone offset)
    - Wrong: "2025-11-20T17:00:00" (ambiguous - is this local time or UTC?)
    
    If you're in a timezone other than UTC (e.g., Pakistan PKT = UTC+5), 
    convert to UTC before passing to this function!
    """
    # Handle question_types: if provided, use it; otherwise fall back to question_type for backward compatibility
    if question_types is None:
        # If question_types not provided, convert single question_type to list
        question_types = [question_type] if question_type else ["Descriptive"]
    
    doc = {
        "recruiter_id": recruiter_id,
        "title": title,
        "description": description,
        "difficulty_level": difficulty_level,
        "num_questions": num_questions,
        "apply_deadline": apply_deadline,
        "num_vacancies": num_vacancies,
        "question_type": question_type,  # Keep for backward compatibility
        "question_types": question_types,  # New: list of question types
        "max_shortlist": max_shortlist,
        "ai_instructions": ai_instructions,
        "invite_rule": invite_rule,  # "Top 5", "Top 10", "Top N", "All"
        "invite_rule_n": invite_rule_n,  # Custom number for "Top N"
        "embedding": embedding,  # LLM embedding vector for matching
        "evaluationConfig": evaluation_config or {
            "criteria": ["technical", "communication", "problemSolving", "confidence", "culturalFit"],
            "strictnessLevel": difficulty_level if difficulty_level in ["Easy", "Moderate", "Strict"] else "Moderate"
        },
        "status": "open",  # open | processed
        "selected_resume_ids": [],
        "created_at": get_utc_now()
    }
    
    # NEW: Add sectioned interview configuration if provided
    if interview_config:
        doc["interview_config"] = interview_config
    
    return doc

def create_resume_document(candidate_name: str, email: str, text: str, features: dict, 
                          file_name: str = None, file_type: str = None, embedding: list = None):
    """
    Create a resume document.
    NOTE: Bias detection has been removed - evaluation is now based solely on technical qualifications.
    """
    return {
        "candidate_name": candidate_name,
        "email": email,
        "text": text,
        "features": features,
        "embedding": embedding,  # LLM embedding vector for matching (generated from sanitized text)
        "uploaded_at": get_utc_now(),
        "file_name": file_name,
        "file_type": file_type
    }

def create_interview_document(jd_id: str, resume_id: str, questions: list, 
                             interview_token: str = None, started_at: str = None,
                             num_questions: int = None, difficulty_level: str = None,
                             question_type: str = None):
    """
    Create an interview document.
    Questions can be in two formats:
    1. Legacy: List of strings or objects (for backward compatibility)
    2. New: List of objects with metadata: [{"id": 0, "type": "MCQ", "question": {...}}, ...]
    """
    # Import here to avoid circular dependencies if any
    from core.constants import InterviewState, DEFAULT_INTERVIEW_Duration_MINUTES
    from datetime import timedelta
    
    start_time = started_at or get_utc_now()
    
    # Calculate hard stop time (Absolute Server Time)
    # Note: start_time is string, need parsing if we want to add delta, 
    # but for simplicity in this helper we might handle it in the service or parse here.
    # Let's keep it simple: initial state is INIT, deadlines set when 'START' is clicked.
    
    return {
        "jd_id": jd_id,
        "resume_id": resume_id,
        "questions": questions,
        "responses": [],  # Will store answers: [{"question_id": 0, "answer": "...", "type": "MCQ"}, ...]
        "scores": [],
        "avg_score": None,
        "interview_token": interview_token,
        "num_questions": num_questions,
        "difficulty_level": difficulty_level,
        "question_type": question_type,  # Primary type or "Mixed"
        
        # -- Orchestration Engine Fields --
        "status": InterviewState.CREATED.value, # Legacy field, synced with state
        "state": InterviewState.CREATED.value,  # FSM State
        "started_at": start_time,
        "completed_at": None,
        
        "interview_expires_at": None,       # Set when user clicks "Start Interview"
        "question_started_at": None,
        "question_duration": None,
        "question_expires_at": None,
        "time_limit_seconds": DEFAULT_INTERVIEW_Duration_MINUTES * 60,
        "question_time_limit_seconds": 300, # 5 mins default, allows per-question override later
        
        "current_question_index": 0,        # Server-authoritative pointer
        "client_ip": None                   # Session binding
    }

def create_application_document(job_id: str, resume_id: str, candidate_name: str, 
                               candidate_email: str, status: str = "New", 
                                ai_match_score: int = 0, screening_id: str = None,
                                match_score_breakdown: dict = None):

    """Create an application document with detailed match score breakdown"""
    return {
        "job_id": job_id,
        "resume_id": resume_id,
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
        "status": status,
        "ai_match_score": ai_match_score,
        "match_score_breakdown": match_score_breakdown or {},  # Detailed breakdown scores
        "screening_id": screening_id,
        "cheater": False,
        "applied_at": get_utc_now(),
        "updated_at": get_utc_now()
    }

def create_notification_document(recipient_id: str, notification_type: str, title: str, 
                                  message: str, link: str = None, metadata: dict = None):
    """Create a notification document"""
    return {
        "recipient_id": recipient_id,
        "type": notification_type,  # "application" | "interview" | "system" | "message"
        "title": title,
        "message": message,
        "link": link,
        "is_read": False,
        "metadata": metadata or {},
        "created_at": get_utc_now()
    }

def create_file_document(candidate_id: str, job_id: str, file_name: str, file_url: str, 
                        file_type: str, file_size: int = None, uploaded_by: str = None):
    """Create a file document"""
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "file_name": file_name,
        "file_url": file_url,
        "file_type": file_type,
        "file_size": file_size,
        "uploaded_by": uploaded_by,
        "uploaded_at": get_utc_now(),
        "version": 1,
        "is_active": True
    }

def create_audit_log_document(user_id: str, action: str, entity_type: str, 
                              entity_id: str = None, details: dict = None, ip_address: str = None):
    """Create an audit log document"""
    return {
        "user_id": user_id,
        "action": action,  # "create", "update", "delete", "login", "logout", etc.
        "entity_type": entity_type,  # "job", "application", "interview", "user", etc.
        "entity_id": entity_id,
        "details": details or {},
        "ip_address": ip_address,
        "timestamp": get_utc_now()
    }

def create_analytics_snapshot_document(recruiter_id: str = None, snapshot_type: str = "daily",
                                      metrics: dict = None):
    """Create an analytics snapshot document"""
    return {
        "recruiter_id": recruiter_id,
        "snapshot_type": snapshot_type,  # "daily", "weekly", "monthly"
        "metrics": metrics or {},
        "snapshot_date": get_utc_now(),
        "created_at": get_utc_now()
    }

def create_scheduled_interview_document(
    recruiter_id: str,
    candidate_id: str,
    candidate_name: str,
    candidate_email: str,
    job_id: str,
    job_title: str,
    interview_datetime: str,
    duration_minutes: int,
    location: str,
    interview_type: str,
    timezone: str,
    calendar_event_id: str = None,
    calendar_event_link: str = None,
    status: str = "scheduled",
    notes: str = None
):
    """Create a scheduled interview document"""
    return {
        "recruiter_id": recruiter_id,
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
        "job_id": job_id,
        "job_title": job_title,
        "interview_datetime": interview_datetime,
        "duration_minutes": duration_minutes,
        "location": location,
        "interview_type": interview_type,  # "one-on-one", "panel", "phone", "video"
        "timezone": timezone,
        "calendar_event_id": calendar_event_id,
        "calendar_event_link": calendar_event_link,
        "status": status,  # "scheduled", "completed", "cancelled", "rescheduled"
        "notes": notes,
        "reminders_sent": {
            "24h": False,
            "1h": False,
            "15m": False
        },
        "created_at": get_utc_now(),
        "updated_at": get_utc_now()
    }

# --- Pydantic Models for Robust Systems ---
from pydantic import BaseModel, Field, EmailStr
from typing import Dict, Any, List, Optional
import uuid

class EmailTask(BaseModel):
    """
    Schema for a persistent email task.
    Stored in 'email_queue' collection.
    """
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED, DEAD_LETTER
    
    # Email Metadata
    to_email: str
    subject: str
    template_name: str
    template_data: Dict[str, Any]
    
    # Retry Logic
    attempts: int = 0
    max_attempts: int = 5
    last_attempt: Optional[datetime] = None
    next_retry: Optional[datetime] = None
    error_log: List[str] = []
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True

def create_email_task_document(to_email: str, subject: str, template_name: str, template_data: dict) -> dict:
    """Helper to create an email task document compatible with the Pydantic model"""
    task = EmailTask(
        to_email=to_email,
        subject=subject,
        template_name=template_name,
        template_data=template_data
    )
    return task.dict()
