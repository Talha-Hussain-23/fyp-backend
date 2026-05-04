"""
AI Orchestrator - Manages fallback chain for question generation and evaluation
Groq → Gemini → Templates
"""

import logging
from typing import List, Dict, Optional
from .groq_service import get_groq_service
from .gemini_service import get_gemini_service

logger = logging.getLogger(__name__)


class AIOrchestrator:
    """
    Orchestrates AI services with intelligent fallback
    Tries Groq first, then Gemini, then template questions
    """
    
    def __init__(self):
        self.groq = None
        self.gemini = None
        self.templates = None
        
        # Initialize services lazily
        try:
            self.groq = get_groq_service()
            logger.info("Groq service initialized")
        except Exception as e:
            logger.warning(f"Groq service unavailable: {e}")
        
        try:
            self.gemini = get_gemini_service()
            logger.info("Gemini service initialized")
        except Exception as e:
            logger.warning(f"Gemini service unavailable: {e}")
    
    async def generate_questions(
        self,
        job_description: str,
        difficulty: str = "medium",
        count: int = 5,
        categories: List[str] = None
    ) -> Dict:
        """
        Generate questions with fallback chain
        
        Returns:
            Dict with questions and provider info
        """
        
        # Try Groq first
        if self.groq:
            try:
                questions = await self.groq.generate_questions(
                    job_description, difficulty, count, categories
                )
                logger.info(f"Generated {len(questions)} questions using Groq")
                return {
                    "questions": questions,
                    "provider": "groq",
                    "fallback_used": False
                }
            except Exception as e:
                logger.warning(f"Groq failed, trying Gemini: {e}")
        
        # Fallback to Gemini
        if self.gemini:
            try:
                questions = await self.gemini.generate_questions(
                    job_description, difficulty, count, categories
                )
                logger.info(f"Generated {len(questions)} questions using Gemini (fallback)")
                return {
                    "questions": questions,
                    "provider": "gemini",
                    "fallback_used": True
                }
            except Exception as e:
                logger.warning(f"Gemini failed, using templates: {e}")
        
        # Final fallback to templates
        logger.warning("All AI providers failed, using template questions")
        from .template_service import get_template_service
        if not self.templates:
            self.templates = get_template_service()
        
        questions = self.templates.get_questions(difficulty, count, categories)
        return {
            "questions": questions,
            "provider": "templates",
            "fallback_used": True
        }
    
    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        expected_keywords: List[str] = None
    ) -> Dict:
        """
        Evaluate answer with fallback chain
        
        Returns:
            Evaluation dict with provider info
        """
        
        # Try Groq first
        if self.groq:
            try:
                evaluation = await self.groq.evaluate_answer(
                    question, answer, expected_keywords
                )
                evaluation["provider"] = "groq"
                evaluation["fallback_used"] = False
                logger.info("Answer evaluated using Groq")
                return evaluation
            except Exception as e:
                logger.warning(f"Groq evaluation failed, trying Gemini: {e}")
        
        # Fallback to Gemini
        if self.gemini:
            try:
                evaluation = await self.gemini.evaluate_answer(
                    question, answer, expected_keywords
                )
                evaluation["provider"] = "gemini"
                evaluation["fallback_used"] = True
                logger.info("Answer evaluated using Gemini (fallback)")
                return evaluation
            except Exception as e:
                logger.warning(f"Gemini evaluation failed, using heuristic: {e}")
        
        # Final fallback to heuristic
        logger.warning("All AI providers failed, using heuristic evaluation")
        from .template_service import get_template_service
        if not self.templates:
            self.templates = get_template_service()
        
        evaluation = self.templates.heuristic_evaluation(answer)
        evaluation["provider"] = "heuristic"
        evaluation["fallback_used"] = True
        return evaluation


# Singleton
_orchestrator = None

def get_ai_orchestrator() -> AIOrchestrator:
    """Get or create AI orchestrator singleton"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AIOrchestrator()
    return _orchestrator
