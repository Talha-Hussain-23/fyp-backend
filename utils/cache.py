"""
Cache Utility (Compatibility Layer)
Bridges the old utils.cache interface to the new core.cache implementation
"""
from core.cache import CacheService as Cache, get_cache_service as get_cache, cached

async def invalidate_cache(key: str):
    """Bridge for legacy invalidate_cache call"""
    cache = get_cache()
    return await cache.delete(key)

__all__ = ['Cache', 'get_cache', 'cached', 'invalidate_cache']
