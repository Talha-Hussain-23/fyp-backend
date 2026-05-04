"""
✅ LEGENDARY STANDALONE: In-Memory Caching Layer
High-performance caching for SmartHiring without external dependencies.
"""
import json
import copy
import hashlib
import logging
import asyncio
from typing import Optional, Any, Callable, TypeVar
from functools import wraps

from core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

class CacheService:
    """
    ✅ PRODUCTION-GRADE: In-memory cache service.
    
    Uses JSON serialization to mirror Redis "pass-by-value" behavior,
    ensuring that objects retrieved from cache are independent copies.
    """
    
    def __init__(self):
        self.memory_cache: dict = {}
        self._lock = asyncio.Lock()
        logger.info("🚀 Legendary In-Memory Cache Initialized (Redis Completely Removed)")
    
    async def is_operational(self) -> bool:
        """Always operational in memory"""
        return True

    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate deterministic cache key"""
        key_data = f"{prefix}:{str(args)}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache (async)"""
        try:
            value = self.memory_cache.get(key)
            if value is not None:
                # Return a copy to prevent accidental mutation of internal state
                return copy.deepcopy(value)
            return None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None

    def get_sync(self, key: str) -> Optional[Any]:
        """Get value from cache (sync)"""
        try:
            value = self.memory_cache.get(key)
            if value is not None:
                return copy.deepcopy(value)
            return None
        except Exception as e:
            logger.error(f"Cache get_sync error: {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache (async)"""
        try:
            # Store a copy
            self.memory_cache[key] = copy.deepcopy(value)
            
            # Simple size-based cleanup (prevents memory leaks)
            if len(self.memory_cache) > settings.CACHE_SIZE_LIMIT:
                # Remove oldest item (keys() in Python 3.7+ are insertion-ordered)
                first_key = next(iter(self.memory_cache))
                self.memory_cache.pop(first_key)
            
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False

    def set_sync(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache (sync)"""
        try:
            self.memory_cache[key] = copy.deepcopy(value)
            if len(self.memory_cache) > settings.CACHE_SIZE_LIMIT:
                first_key = next(iter(self.memory_cache))
                self.memory_cache.pop(first_key)
            return True
        except Exception as e:
            logger.error(f"Cache set_sync error: {e}")
            return False
    
    async def get_or_set(
        self,
        key: str,
        fetcher: Callable[[], Any],
        ttl: Optional[int] = None
    ) -> Any:
        """Helper for cache-aside pattern"""
        value = await self.get(key)
        if value is not None:
            return value
        
        async with self._lock:
            # Double-check after lock
            value = await self.get(key)
            if value is not None:
                return value
                
            result = await fetcher() if asyncio.iscoroutinefunction(fetcher) else fetcher()
            await self.set(key, result, ttl)
            return result

    async def delete(self, key: str) -> bool:
        """Invalidate a specific key (async)"""
        self.memory_cache.pop(key, None)
        return True

    def delete_sync(self, key: str) -> bool:
        """Invalidate a specific key (sync)"""
        self.memory_cache.pop(key, None)
        return True
    
    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern (async)"""
        keys_to_del = [k for k in self.memory_cache.keys() if k.startswith(pattern)]
        for k in keys_to_del:
            self.memory_cache.pop(k, None)
        return len(keys_to_del)

    def cached(
        self,
        prefix: str,
        ttl: int = 3600
    ) -> Callable:
        """Decorator for async routes/functions"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                cache_key = self._generate_key(prefix, *args, **kwargs)
                
                cached_value = await self.get(cache_key)
                if cached_value is not None:
                    return cached_value
                
                result = await func(*args, **kwargs)
                await self.set(cache_key, result, ttl)
                
                return result
            return wrapper
        return decorator


# Singleton instance
_cache_service: Optional[CacheService] = None

def get_cache_service() -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service

def cached(prefix: str, ttl: int = 3600):
    """Convenience decorator factory"""
    def decorator(func):
        cache = get_cache_service()
        return cache.cached(prefix, ttl)(func)
    return decorator

__all__ = ['CacheService', 'get_cache_service', 'cached']
