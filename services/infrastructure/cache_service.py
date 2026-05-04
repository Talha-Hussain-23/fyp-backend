"""
AI Service Caching Layer
Cache AI-generated content to improve performance and reduce API costs
"""
import logging
from typing import Optional, List, Dict, Any
from core.cache import get_cache_service, cached

logger = logging.getLogger(__name__)


class AICache:
    """Caching layer for AI service responses"""
    
    def __init__(self):
        self.cache = get_cache_service()
        self.default_ttl = 3600  # 1 hour
        self.question_cache_ttl = 7200  # 2 hours for questions
    
    def cache_questions(
        self,
        jd_preview: str,
        num_questions: int,
        difficulty: str,
        question_type: str,
        questions: List[Any]
    ) -> bool:
        """Cache generated questions"""
        try:
            cache_key = f"questions:{hash(jd_preview)}:{num_questions}:{difficulty}:{question_type}"
            return self.cache.set(cache_key, questions, self.question_cache_ttl)
        except Exception as e:
            logger.error(f"Failed to cache questions: {e}")
            return False
    
    def get_cached_questions(
        self,
        jd_preview: str,
        num_questions: int,
        difficulty: str,
        question_type: str
    ) -> Optional[List[Any]]:
        """Get cached questions if available"""
        try:
            cache_key = f"questions:{hash(jd_preview)}:{num_questions}:{difficulty}:{question_type}"
            return self.cache.get(cache_key)
        except Exception as e:
            logger.error(f"Failed to get cached questions: {e}")
            return None
    
    def cache_evaluation(
        self,
        question: str,
        response: str,
        evaluation: Dict[str, Any]
    ) -> bool:
        """Cache evaluation result"""
        try:
            cache_key = f"eval:{hash(question)}:{hash(response)}"
            return self.cache.set(cache_key, evaluation, self.default_ttl)
        except Exception as e:
            logger.error(f"Failed to cache evaluation: {e}")
            return False
    
    def get_cached_evaluation(
        self,
        question: str,
        response: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached evaluation if available"""
        try:
            cache_key = f"eval:{hash(question)}:{hash(response)}"
            return self.cache.get(cache_key)
        except Exception as e:
            logger.error(f"Failed to get cached evaluation: {e}")
            return None
    
    def invalidate_job_questions(self, jd_id: str):
        """Invalidate all cached questions for a job"""
        try:
            pattern = f"questions:*{jd_id}*"
            self.cache.clear(pattern)
            logger.info(f"Invalidated question cache for job {jd_id}")
        except Exception as e:
            logger.error(f"Failed to invalidate cache: {e}")


# Singleton instance
_ai_cache = None

def get_ai_cache() -> AICache:
    """Get or create AI cache instance"""
    global _ai_cache
    if _ai_cache is None:
        _ai_cache = AICache()
    return _ai_cache


__all__ = ['AICache', 'get_ai_cache']
