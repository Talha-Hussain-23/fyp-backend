"""
Candidate Schemas
Models for resume upload and candidate applications
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr


class ResumeFeatures(BaseModel):
    """Extracted resume features."""
    skills: List[str] = []
    experience_years: float = 0.0
    education_level: Optional[str] = None
    certifications: List[str] = []


class ResumeUploadResponse(BaseModel):
    """Response after resume upload."""
    id: str
    filename: str
    candidate_name: Optional[str] = None
    email: Optional[EmailStr] = None
    features: Optional[ResumeFeatures] = None
    upload_time: str


class ApplyRequest(BaseModel):
    """Job application request."""
    resume_id: str
    cover_letter: Optional[str] = None


class ApplicationStatusUpdate(BaseModel):
    """Update application status."""
    status: str
    send_email: bool = False
    feedback: Optional[str] = None
