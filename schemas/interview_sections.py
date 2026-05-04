"""
Interview Sections Schema
Pydantic models for sectioned interview configuration
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal


class SectionConfig(BaseModel):
    """Configuration for a single interview section"""
    type: Literal["Descriptive", "MCQ", "Code"]
    enabled: bool = True
    num_questions: int = Field(ge=1, le=20, description="Number of questions in this section")
    weight: int = Field(ge=0, le=100, description="Percentage weight in final score")
    time_per_question: int = Field(ge=30, le=3600, description="Time per question in seconds")
    difficulty: Literal["Easy", "Moderate", "Hard"] = "Moderate"
    language: Optional[str] = Field(None, description="Programming language for Code section")
    instructions: Optional[str] = Field(None, description="Custom instructions for this section")
    
    @field_validator('language')
    @classmethod
    def validate_code_language(cls, v, info):
        """Ensure Code section has a language specified"""
        values = info.data
        if values.get('type') == 'Code' and values.get('enabled') and not v:
            raise ValueError("Code section must specify a programming language")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "Descriptive",
                "enabled": True,
                "num_questions": 3,
                "weight": 40,
                "time_per_question": 180,
                "difficulty": "Moderate",
                "instructions": "Answer in detail with examples"
            }
        }


class InterviewConfig(BaseModel):
    """Complete interview configuration with multiple sections"""
    sections: List[SectionConfig] = Field(min_items=1, max_items=10)
    
    @field_validator('sections')
    @classmethod
    def validate_sections(cls, sections):
        """Validate interview sections configuration"""
        # At least one section must be enabled
        enabled_sections = [s for s in sections if s.enabled]
        if not enabled_sections:
            raise ValueError("At least one interview section must be enabled")
        
        # Total weight must equal 100%
        total_weight = sum(s.weight for s in enabled_sections)
        if total_weight != 100:
            raise ValueError(
                f"Total weight of enabled sections must be 100%, got {total_weight}%"
            )
        
        # Check for duplicate section types
        enabled_types = [s.type for s in enabled_sections]
        if len(enabled_types) != len(set(enabled_types)):
            raise ValueError("Cannot have duplicate section types enabled")
        
        # Validate Code sections have language
        for section in enabled_sections:
            if section.type == "Code" and not section.language:
                raise ValueError("Code section must specify a programming language")
        
        return sections
    
    @property
    def total_questions(self) -> int:
        """Calculate total number of questions across all enabled sections"""
        return sum(s.num_questions for s in self.sections if s.enabled)
    
    @property
    def total_time(self) -> int:
        """Calculate total interview time in seconds"""
        return sum(
            s.num_questions * s.time_per_question 
            for s in self.sections if s.enabled
        )
    
    @property
    def enabled_section_types(self) -> List[str]:
        """Get list of enabled section types"""
        return [s.type for s in self.sections if s.enabled]
    
    class Config:
        json_schema_extra = {
            "example": {
                "sections": [
                    {
                        "type": "Descriptive",
                        "enabled": True,
                        "num_questions": 3,
                        "weight": 40,
                        "time_per_question": 180,
                        "difficulty": "Moderate"
                    },
                    {
                        "type": "MCQ",
                        "enabled": True,
                        "num_questions": 5,
                        "weight": 30,
                        "time_per_question": 60,
                        "difficulty": "Moderate"
                    },
                    {
                        "type": "Code",
                        "enabled": True,
                        "num_questions": 2,
                        "weight": 30,
                        "time_per_question": 600,
                        "difficulty": "Hard",
                        "language": "Python"
                    }
                ]
            }
        }


class InterviewSectionResponse(BaseModel):
    """Response model for interview section data"""
    type: str
    enabled: bool
    status: str  # not_started, in_progress, completed
    current_question_index: int
    num_questions: int
    weight: int
    section_score: float = 0.0
    completion_percentage: int = 0
    time_spent: int = 0
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "Descriptive",
                "enabled": True,
                "status": "completed",
                "current_question_index": 3,
                "num_questions": 3,
                "weight": 40,
                "section_score": 8.2,
                "completion_percentage": 100,
                "time_spent": 435
            }
        }
