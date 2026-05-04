"""
Proctoring Session Manager
Handles in-memory state management for active proctoring sessions.
"""
from datetime import datetime, timezone
import structlog
from collections import defaultdict
from typing import Dict, Any, Optional
from core.cache import get_cache_service
import asyncio

logger = structlog.get_logger(__name__)

class SessionManager:
    """
    ✅ LEGENDARY: Manages active proctoring sessions in-memory.
    Persistence of major violations and session summaries is handled via MongoDB.
    """
    
    def __init__(self, db):
        self.db = db
        self.cache = get_cache_service()
        self.CACHE_PREFIX = "proctoring:session:"
        self.RATE_LIMIT_PREFIX = "proctoring:rate:"
        
        # High-speed local lookup for critical path
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        
        self._lock = asyncio.Lock()
        
    def _get_cache_key(self, client_id: str) -> str:
        return f"{self.CACHE_PREFIX}{client_id}"

    async def create_session(self, client_id: str, interview_id: str, user_id: str = None, token: str = None, candidate_name: str = "Unknown") -> Dict[str, Any]:
        """Initialize a new proctoring session"""
        async with self._lock:
            session = {
                'session_id': client_id,
                'interview_id': interview_id,
                'candidate_name': candidate_name,
                'started_at': datetime.now(timezone.utc).isoformat(),
                'violation_count': 0,
                'last_sequence': -1,
                'auth_token': token,
                'user_id': user_id,
                'status': 'active',
                'last_heartbeat': datetime.now(timezone.utc).isoformat()
            }
            
            # Save to Cache (In-Memory)
            await self.cache.set(self._get_cache_key(client_id), session, ttl=3600)
            
            # Local reference for speed
            self.active_sessions[client_id] = session
            
            # Persistent Audit Log in MongoDB
            try:
                await self.db.proctoring_sessions.insert_one({
                    'session_id': client_id,
                    'interview_id': interview_id,
                    'started_at': session['started_at'],
                    'status': 'active'
                })
            except Exception as e:
                logger.error("session_audit_save_failed", error=str(e))
                
            return session

    async def get_session(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data by client_id (Local -> Cache)"""
        async with self._lock:
            # Check primary local map
            if client_id in self.active_sessions:
                return self.active_sessions[client_id]
            
            # Check secondary cache
            session = await self.cache.get(self._get_cache_key(client_id))
            if session:
                self.active_sessions[client_id] = session
                return session
                
            return None

    async def update_session(self, client_id: str, updates: Dict[str, Any]):
        """Update session data and sync to cache"""
        async with self._lock:
            session = self.active_sessions.get(client_id)
            if not session:
               session = await self.cache.get(self._get_cache_key(client_id))
            
            if session:
                session.update(updates)
                await self.cache.set(self._get_cache_key(client_id), session, ttl=3600)
                self.active_sessions[client_id] = session

    async def end_session(self, client_id: str):
        """End a session and cleanup"""
        async with self._lock:
            session = self.active_sessions.get(client_id)
            if not session:
               session = await self.cache.get(self._get_cache_key(client_id))
               
            if session:
                # Persistent update in MongoDB
                try:
                    await self.db.proctoring_sessions.update_one(
                        {'session_id': client_id},
                        {'$set': {
                            'ended_at': datetime.now(timezone.utc).isoformat(),
                            'total_violations': session.get('violation_count', 0),
                            'status': 'ended'
                        }}
                    )
                except Exception as e:
                    logger.error("session_end_save_failed", error=str(e))
                
                # Cleanup cache and memory
                await self.cache.delete(self._get_cache_key(client_id))
                
                if client_id in self.active_sessions:
                    del self.active_sessions[client_id]
                

    async def register_connection(self, client_id: str, token: str = None, user: Any = None):
        """Register a new socket connection (pre-session)"""
        async with self._lock:
            user_id = None
            if user:
                extracted_id = getattr(user, 'id', user.get('id', user.get('sub')) if isinstance(user, dict) else None)
                user_id = str(extracted_id) if extracted_id else None
                
            session = {
                'status': 'connected',
                'auth_token': token,
                'user_id': user_id,
                'last_heartbeat': datetime.now(timezone.utc).isoformat()
            }
            self.active_sessions[client_id] = session
            await self.cache.set(self._get_cache_key(client_id), session, ttl=600)

    async def terminate_session(self, client_id: str, reason: str):
        """
        Terminate and lock a proctoring session (Sync with MongoDB)
        """
        from bson import ObjectId
        
        async with self._lock:
            session = self.active_sessions.get(client_id)
            if not session:
               session = await self.cache.get(self._get_cache_key(client_id))
               
            if not session:
                logger.warning("no_session_for_termination", client_id=client_id)
                return
            
            interview_id = session.get('interview_id')
            
            # Update session status
            session['status'] = 'terminated'
            session['terminated_at'] = datetime.now(timezone.utc).isoformat()
            session['termination_reason'] = reason
            
            await self.cache.set(self._get_cache_key(client_id), session, ttl=3600)
            self.active_sessions[client_id] = session
            
            try:
                interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
                if interview:
                    all_scores = interview.get("scores", [])
                    avg_score = round(sum(s.get("score", 0) for s in all_scores) / len(all_scores), 1) if all_scores else 0
                    
                    # LOCK INTERVIEW STATE PERMANENTLY IN MONGODB
                    await self.db.interviews.update_one(
                        {'_id': ObjectId(interview_id)},
                        {'$set': {
                            'session_locked': True,
                            'session_lock_reason': reason,
                            'locked_at': datetime.now(timezone.utc).isoformat(),
                            'locked_by': 'proctoring_system',
                            'proctoring_terminated': True,
                            'status': 'terminated',
                            'is_completed': True,
                            'avg_score': avg_score,
                            'final_score': avg_score
                        }}
                    )
                
                    # FIX #3: Only write interview_score to applications if we actually have scores.
                    # If all_scores is empty, evaluation hasn't run yet (async AI eval is still pending).
                    # Writing avg_score * 10 = 0 here overwrites with a false zero.
                    # evaluate_terminated_interview_background will call _sync_interview_results_to_application
                    # which correctly sets the score after evaluation completes.
                    app_update_fields = {
                        "interview_status": "terminated",
                        "interview_termination_reason": reason,
                        "interview_terminated_at": datetime.now(timezone.utc).isoformat(),
                        "is_completed": True,
                    }
                    if all_scores:  # Only write score if we have actual evaluated scores
                        # Store on 0-100 scale (avg_score is 0-10)
                        app_update_fields["interview_score"] = round(avg_score * 10, 1)
                    
                    await self.db.applications.update_one(
                        {
                            "job_id": str(interview.get("jd_id")),
                            "resume_id": str(interview.get("resume_id"))
                        },
                        {"$set": app_update_fields}
                    )
                
                logger.critical("termination_synced", interview_id=interview_id)
            except Exception as e:
                logger.error("termination_sync_failed", error=str(e))
            
            try:
                await self.db.proctoring_sessions.update_one(
                    {'session_id': client_id},
                    {'$set': {
                        'status': 'terminated',
                        'terminated_at': session['terminated_at'],
                        'termination_reason': reason
                    }}
                )
            except Exception as e:
                logger.error("proctoring_session_update_failed", error=str(e))
    
    async def remove_connection(self, client_id: str):
        """Remove a connection if it hasn't started a session or force cleanup"""
        session = await self.get_session(client_id)
        if session:
            if session.get('status') == 'active':
                await self.end_session(client_id)
            else:
                async with self._lock:
                    await self.cache.delete(self._get_cache_key(client_id))
                    if client_id in self.active_sessions:
                        del self.active_sessions[client_id]

    async def garbage_collect_stale_sessions(self, max_idle_minutes: int = 5):
        """Clean up stale sessions from memory"""
        now = datetime.now(timezone.utc)
        to_remove = []
        
        keys = list(self.active_sessions.keys())
        
        for client_id in keys:
            session = self.active_sessions.get(client_id, {})
            last_hb = session.get('last_heartbeat')
            if not last_hb:
                try:
                    started_at = datetime.fromisoformat(session.get('started_at', now.isoformat()))
                    if (now - started_at).total_seconds() > max_idle_minutes * 60:
                        to_remove.append(client_id)
                except:
                    to_remove.append(client_id)
                continue
            
            try:
                if isinstance(last_hb, str):
                     last_hb = datetime.fromisoformat(last_hb)
                idle_seconds = (now - last_hb).total_seconds()
                if idle_seconds > max_idle_minutes * 60:
                    to_remove.append(client_id)
            except Exception as e:
                logger.error("gc_error", client_id=client_id, error=str(e))
                to_remove.append(client_id)

        for client_id in to_remove:
            await self.remove_connection(client_id)
        
        return len(to_remove)

    async def can_resume_session(self, interview_id: str) -> bool:
        """Check if interview status in MongoDB allows resumption"""
        from bson import ObjectId
        try:
            logger.debug("resume_check", interview_id=interview_id)
            interview = await self.db.interviews.find_one({'_id': ObjectId(interview_id)})
            if not interview:
                logger.debug("resume_check_not_found", interview_id=interview_id)
                return False
            
            logger.debug("resume_check_state", status=interview.get('status'), state=interview.get('state'), proctoring_terminated=interview.get('proctoring_terminated'), session_locked=interview.get('session_locked'))
            
            if interview.get('proctoring_terminated') or interview.get('session_locked'):
                logger.warning("resume_blocked_locked", interview_id=interview_id)
                return False
            
            if interview.get('status') in ['completed', 'disqualified']:
                logger.debug("resume_blocked_status", interview_id=interview_id, status=interview.get('status'))
                return False
            
            logger.debug("resume_allowed", interview_id=interview_id)
            return True
        except Exception as e:
            logger.error("resume_check_error", error=str(e))
            return False
