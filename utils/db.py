"""
Enhanced Database Connection with Motor (Async MongoDB)
Refactored for High-Performance Async I/O
"""
import time
import logging
import structlog
from typing import Optional, Any
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticClient, AgnosticDatabase
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure

from core.config import settings

logger = structlog.get_logger(__name__)

# Global MongoDB objects for reuse
_mongo_client: Optional[AsyncIOMotorClient] = None
_db_instance: Optional[AgnosticDatabase] = None


class DatabaseConnectionManager:
    """Manages Async MongoDB connection with health monitoring and auto-recovery"""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AgnosticDatabase] = None
        self.connection_attempts = 0
        self.last_health_check = 0
        self.health_check_interval = 60  # seconds
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ServerSelectionTimeoutError, ConnectionFailure)),
        reraise=True
    )
    async def connect(self) -> bool:
        """
        Connect to MongoDB using Motor with retry logic
        
        Returns:
            bool: True if connection successful
        """
        try:
            mongo_uri = settings.MONGODB_URI
            
            # Motor Async Client Configuration
            self.client = AsyncIOMotorClient(
                mongo_uri,
                serverSelectionTimeoutMS=15000,
                connectTimeoutMS=30000,
                socketTimeoutMS=45000,
                maxPoolSize=settings.MAX_POOL_SIZE,
                minPoolSize=settings.MIN_POOL_SIZE,
                maxIdleTimeMS=settings.MAX_IDLE_TIME_MS,
                retryWrites=True,
                retryReads=True,
                w='majority',
                journal=True
            )
            
            # Test connection with ping
            await self.client.admin.command('ping')
            
            # Store references
            self.db = self.client[settings.DATABASE_NAME]
            
            self.connection_attempts += 1
            logger.info("mongodb_async_connected", attempt=self.connection_attempts, database=settings.DATABASE_NAME)
            
            return True
            
        except ServerSelectionTimeoutError as e:
            logger.error(f"❌ MongoDB async connection timeout: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ MongoDB async connection failed: {e}")
            raise
    
    async def is_healthy(self) -> bool:
        """Check if database connection is healthy (non-blocking)"""
        try:
            if self.client is None or self.db is None:
                return False
            
            # Throttle health checks
            current_time = time.time()
            if current_time - self.last_health_check < self.health_check_interval:
                return True
            
            # Perform health check
            await self.client.admin.command('ping')
            self.last_health_check = current_time
            return True
            
        except Exception as e:
            logger.warning(f"⚠️  Database async health check failed: {e}")
            return False
    
    async def reconnect_if_needed(self):
        """Reconnect if connection is unhealthy"""
        if not await self.is_healthy():
            logger.warning("🔄 Attempting to reconnect to database (async)...")
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"❌ Async reconnection failed: {e}")
    
    def get_database(self) -> AgnosticDatabase:
        """Get database instance reference"""
        return self.db
    
    def close(self):
        """Close database connection"""
        if self.client:
            self.client.close()
            logger.info("🔌 MongoDB async connection closed")


# Single global manager
_connection_manager: Optional[DatabaseConnectionManager] = None


async def get_connection_manager() -> DatabaseConnectionManager:
    """Get or create connection manager asynchronously"""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = DatabaseConnectionManager()
        await _connection_manager.connect()
    return _connection_manager


async def get_db():
    """
    FastAPI dependency: Returns async database instance
    
    Yields:
        AgnosticDatabase: Motor database instance
    """
    manager = await get_connection_manager()
    db = manager.get_database()
    
    if db is None:
        await manager.connect()
        db = manager.get_database()
        
    return db


async def check_database_health() -> dict:
    """
    Check database health and return status
    
    Returns:
        dict: Health status information
    """
    manager = await get_connection_manager()
    
    try:
        is_healthy = await manager.is_healthy()
        
        if is_healthy:
            # Get server info
            server_info = await manager.client.server_info()
            
            return {
                "status": "healthy",
                "connected": True,
                "version": server_info.get("version", "unknown"),
                "connection_attempts": manager.connection_attempts,
                "database": manager.db.name if manager.db else "unknown"
            }
        else:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": "Async health check failed"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "error": str(e)
        }


async def get_client() -> AsyncIOMotorClient:
    """
    Get MongoDB client instance (backward compatibility)
    
    Returns:
        AsyncIOMotorClient: MongoDB client
    """
    manager = await get_connection_manager()
    return manager.client


from pymongo import MongoClient
from pymongo.database import Database

_sync_client: Optional[MongoClient] = None

def get_db_sync() -> Database:
    """Synchronous database dependency (Legacy)"""
    global _sync_client
    if _sync_client is None:
        _sync_client = MongoClient(settings.MONGODB_URI)
    return _sync_client[settings.DATABASE_NAME]

__all__ = [
    'get_db',
    'get_db_sync',
    'get_client',
    'get_connection_manager',
    'check_database_health',
    'DatabaseConnectionManager'
]

