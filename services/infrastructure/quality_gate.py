"""
AI Quality Gate Service
Implements "AI-on-AI" critique loops to validate generated content.
Uses the Governance Layer (PromptRegistry) for prompts.
"""
import logging
import json
from typing import Dict, Tuple, Optional
from core.governance.prompts import PromptRegistry
from services.ai.ai_provider import ai_service
from services.interview import evaluation  # Reuse sanitize/validation logic if needed

logger = logging.getLogger(__name__)

class QualityGate:
    """
    Validates AI-generated content against strict quality standards.
    """
    
    @staticmethod
    async def validate_question(question: str, job_title: str) -> Tuple[bool, str, Dict]:
        """
        Critique a generated interview question.
        Returns: (is_valid, reason, detailed_metrics)
        """
        try:
            # 1. Fetch "The Critic" Prompt
            prompt_template = PromptRegistry.get("question_quality_gate", "v1.0.0")
            
            # 2. Render Prompt
            prompt_text = PromptRegistry.render(
                "question_quality_gate", 
                "v1.0.0", 
                question=question,
                job_title=job_title
            )
            
            # 3. Call AI Service (The Critic)
            # Use 'generate_json' to enforce structure
            critic_response = await ai_service.generate_json(
                prompt=prompt_text,
                schema={
                    "is_valid": "boolean",
                    "quality_score": "number",
                    "issues": "array of strings",
                    "reason": "string"
                }
            )
            
            # 4. Parse Decision
            is_valid = critic_response.get("is_valid", False)
            score = critic_response.get("quality_score", 0)
            issues = critic_response.get("issues", [])
            reason = critic_response.get("reason", "No reason provided")
            
            # Enforce strict score threshold (e.g., 7/10)
            if score < 7:
                is_valid = False
                reason = f"Quality Score {score}/10 too low. Issues: {', '.join(issues)}"
            
            logger.info(f"Quality Gate: Q='{question[:30]}...' -> Valid={is_valid} (Score={score})")
            
            return is_valid, reason, critic_response

        except Exception as e:
            logger.error(f"Quality Gate Check Failed: {e}")
            # Fail open or closed? 
            # For high security, Fail Closed (return False).
            # For usability, Fail Open (return True with warning).
            # Ultra Deep Professional -> Fail Closed.
            return False, f"Validation Error: {str(e)}", {}

# Singleton
quality_gate = QualityGate()
