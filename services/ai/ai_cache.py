"""
AI Response Cache
Caches AI-generated questions and evaluations for faster responses
"""

from functools import lru_cache
from typing import Dict, List, Optional
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# In-memory cache for AI responses
_ai_cache: Dict[str, any] = {}


def generate_cache_key(prompt: str, model: str = "default") -> str:
    """Generate cache key from prompt"""
    content = f"{model}:{prompt}"
    return hashlib.md5(content.encode()).hexdigest()


def get_cached_ai_response(prompt: str, model: str = "default") -> Optional[any]:
    """Get cached AI response"""
    cache_key = generate_cache_key(prompt, model)
    return _ai_cache.get(cache_key)


def cache_ai_response(prompt: str, response: any, model: str = "default"):
    """Cache AI response"""
    cache_key = generate_cache_key(prompt, model)
    _ai_cache[cache_key] = response
    
    # Limit cache size to 1000 entries
    if len(_ai_cache) > 1000:
        # Remove oldest 100 entries
        keys_to_remove = list(_ai_cache.keys())[:100]
        for key in keys_to_remove:
            del _ai_cache[key]
    
    logger.debug(f"Cached AI response (cache size: {len(_ai_cache)})")


def clear_ai_cache():
    """Clear all cached responses"""
    global _ai_cache
    _ai_cache = {}
    logger.info("AI cache cleared")


def get_cache_stats() -> Dict:
    """Get cache statistics"""
    return {
        "size": len(_ai_cache),
        "max_size": 1000
    }
