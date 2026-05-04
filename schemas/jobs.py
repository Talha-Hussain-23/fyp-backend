"""
Job Description Schemas
Models for job posting and management
"""
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from schemas.interview_sections import InterviewConfig, SectionConfig  # Fix: Top-level import



class JobStatus(str, Enum):
    """Job status enumeration"""
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    FILLED = "filled"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ClosedReason(str, Enum):
    """Reason for job closure"""
    DEADLINE_PASSED = "deadline_passed"
    POSITION_FILLED = "position_filled"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    NO_SUITABLE_CANDIDATES = "no_suitable_candidates"
    OTHER = "other"


class JDBase(BaseModel):
    """Base job description fields."""
    title: str = Field(..., min_length=3, max_length=100)
    description: str = Field(..., min_length=10)
    difficulty_level: str = "Moderate"
    num_questions: int = Field(default=5, ge=1, le=20)
    num_vacancies: int = Field(default=1, ge=1)
    start_date: Optional[str] = None  # ISO8601 string - For Scheduling
    apply_deadline: Optional[str] = None  # ISO8601 string - End Date
    question_types: Optional[List[str]] = None
    ai_instructions: Optional[str] = None
    
    # Legacy support
    question_type: Optional[str] = None


class JDCreate(JDBase):
    """Job creation model."""
    max_shortlist: int = 10
    invite_rule: str = "Top 10"
    invite_rule_n: Optional[int] = None
    
    # NEW: Sectioned interview configuration
    interview_config: Optional['InterviewConfig'] = None  # Forward reference

    @field_validator("invite_rule")
    @classmethod
    def validate_invite_rule(cls, v: str) -> str:
        allowed = ["All", "Top 5", "Top 10", "Top N"]
        if v not in allowed:
            raise ValueError(f"invite_rule must be one of {allowed}")
        return v
    
    @field_validator('interview_config', mode='before')
    @classmethod
    def ensure_interview_config(cls, v, info):
        """Create default interview_config if not provided (backward compatibility)"""
        values = info.data
        if v is None:
            # Fix: Use top-level imports
            
            # Get legacy fields
            num_questions = values.get('num_questions', 5)
            difficulty = values.get('difficulty_level', 'Moderate')
            if difficulty == 'Medium':
                difficulty = 'Moderate'
            question_types = values.get('question_types')
            legacy_type = values.get('question_type')
            
            if not question_types:
                if legacy_type:
                    question_types = [legacy_type]
                else:
                    question_types = ['Descriptive']
            
            # Create default sections based on legacy fields
            sections = []
            enabled_count = len(question_types)
            weight_per_section = 100 // enabled_count if enabled_count > 0 else 100
            
            for q_type in question_types:
                if q_type == 'Descriptive':
                    sections.append(SectionConfig(
                        type='Descriptive',
                        num_questions=num_questions,
                        weight=weight_per_section,
                        time_per_question=180,
                        difficulty=difficulty
                    ))
                elif q_type == 'MCQ':
                    sections.append(SectionConfig(
                        type='MCQ',
                        num_questions=num_questions,
                        weight=weight_per_section,
                        time_per_question=60,
                        difficulty=difficulty
                    ))
                elif q_type == 'Code':
                    sections.append(SectionConfig(
                        type='Code',
                        num_questions=num_questions,
                        weight=weight_per_section,
                        time_per_question=600,
                        difficulty=difficulty,
                        language="Python"
                    ))
            
            # Ensure total weight is 100
            if sections:
                current_total = sum(s.weight for s in sections)
                if current_total != 100:
                    sections[-1].weight += (100 - current_total)
            else:
                # Fallback to Descriptive if somehow empty
                sections.append(SectionConfig(
                    type='Descriptive',
                    num_questions=num_questions,
                    weight=100,
                    time_per_question=180,
                    difficulty=difficulty
                ))
            
            v = InterviewConfig(sections=sections)
        
        return v
    
    @model_validator(mode='after')
    def sync_question_types_with_config(self):
        """
        CRITICAL FIX: Ensure question_types matches interview_config.enabled_section_types
        This prevents Descriptive questions from being generated when only MCQs are selected
        Uses model_validator with mode='after' to run AFTER all field validators
        """
        # If interview_config exists and has sections, derive question_types from it
        if self.interview_config and hasattr(self.interview_config, 'sections'):
            enabled_types = [s.type for s in self.interview_config.sections if s.enabled]
            if enabled_types:
                # Override question_types to match the actual enabled sections
                self.question_types = enabled_types
        
        return self



class JDUpdate(BaseModel):
    """Job update model."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # "open", "closed", "draft", "filled", "paused", "archived", "scheduled"
    difficulty_level: Optional[str] = None
    num_questions: Optional[int] = None
    num_vacancies: Optional[int] = None
    start_date: Optional[str] = None
    apply_deadline: Optional[str] = None
    question_types: Optional[List[str]] = None
    ai_instructions: Optional[str] = None
    invite_rule: Optional[str] = None
    invite_rule_n: Optional[int] = None
    closed_reason: Optional[str] = None  # Reason for closure
    interview_config: Optional['InterviewConfig'] = None  # NEW: Allow updating interview config

    @field_validator("invite_rule")
    @classmethod
    def validate_invite_rule(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = ["All", "Top 5", "Top 10", "Top N"]
        if v not in allowed:
            raise ValueError(f"invite_rule must be one of {allowed}")
        return v
    
    @model_validator(mode='after')
    def sync_question_types_with_config_update(self):
        """
        CRITICAL FIX: Ensure question_types matches interview_config.enabled_section_types
        Same fix as JDCreate to ensure consistency during job updates
        Uses model_validator with mode='after' to run AFTER all field validators
        """
        # If interview_config exists and has sections, derive question_types from it
        if self.interview_config and hasattr(self.interview_config, 'sections'):
            enabled_types = [s.type for s in self.interview_config.sections if s.enabled]
            if enabled_types:
                # Override question_types to match the actual enabled sections
                self.question_types = enabled_types
        
        return self


class JDResponse(JDBase):
    """Job response model."""
    id: str
    recruiter_id: str
    status: str = "open"
    interview_config: Optional[dict] = None  # Sectioned interview configuration
    created_at: datetime
    updated_at: Optional[datetime] = None
    views: int = 0
    applicant_count: int = 0
    recruiter_name: Optional[str] = None
    
    # Enterprise lifecycle fields
    closed_reason: Optional[str] = None
    closed_at: Optional[datetime] = None
    archived: bool = False
    archived_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class JobStatusUpdate(BaseModel):
    """Simple status update."""
    status: str
    send_email: bool = False
    closed_reason: Optional[str] = None  # Required when closing a job
