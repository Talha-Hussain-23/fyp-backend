"""
YOLOv8-based Proctoring Service
Detects persons, phones, laptops, books, and other objects in real-time
"""

# ✅ Suppress all warnings for clean startup
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['GLOG_minloglevel'] = '3'

import warnings
warnings.filterwarnings('ignore')


import cv2
import numpy as np
import base64
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import logging
from collections import deque
import hashlib

# Face Pose Detection removed as requested
FACE_POSE_AVAILABLE = False

from core.cache import get_cache_service

logger = logging.getLogger(__name__)


class ProctoringService:
    """
    Advanced proctoring service using YOLOv8 for real-time object detection
    """
        
    def __init__(self, model_path='ml_models/yolov8n.pt', confidence_threshold=0.2):
        """
    
        Args:
            model_path: Path to YOLOv8 model (default: nano version for speed)
            confidence_threshold: Minimum confidence for detections (default: 0.2)
        """
        try:
            self.confidence_threshold = confidence_threshold
            
            # ✅ ENTERPRISE: Track detection statistics
            self._detection_stats = {
                'total_frames': 0,
                'total_violations': 0,
                'avg_confidence': {},
                'detection_count': {}
            }
            

            
            # ✅ CONSECUTIVE_FRAMES_REQUIRED: Hardened stability (3 frames ≈ 1.5s-2s)
            # This prevents flickering or brief camera glitches from triggering false failures.
            self.CONSECUTIVE_FRAMES_REQUIRED = 2 # Reduced to 2 frames for highly responsive feedback
            
            # ✅ PHASE 1: Duration-based violation tracking thresholds
            # ✅ FIXED: Reduced object threshold for responsive detection
            self.HEAD_POSE_DURATION_THRESHOLD = 3.0  # Reduced for better responsiveness
            self.OBJECT_DURATION_THRESHOLD = 0.5      # Reduced to 0.5s for professional real-time feel
            
            self.HEAD_POSE_VIOLATIONS = set()
            self.OBJECT_VIOLATIONS = set() 
            self.INSTANT_VIOLATIONS = set()
            
            self.pose_detector = None
            
            # ✅ ENTERPRISE: Use CacheService for high-speed state management
            self.cache = get_cache_service()
            self._cache_prefix = "proctoring:v2:"
            self.BUFFER_SIZE = 5
            
            # ✅ PHASE 8: Standalone In-Memory State (Turbo Mode)
            # This eliminates Redis latency in the hot path
            self._session_cache = {}
            
            # ✅ WARMUP: Pre-heat engines to avoid cold-start latency
            self.warmup()
            
        except Exception as e:
            logger.error(f"Failed to initialize Proctoring Service: {e}")
            raise

    async def process_frame(self, frame_data: str, session_id: str = None, frame_index: int = None) -> Dict[str, Any]:
        """
        Stubbed process_frame: Vision proctoring is disabled.
        """
        return {
            'violations': [],
            'focus_warnings': [],
            'person_count': 1, # Assume 1 for compatibility
            'annotated_frame': None,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'has_violations': False,
            'processing_time_ms': 0
        }

    def warmup(self):
        """Warmup disabled: Vision proctoring is removed."""
        logger.info("ℹ️ ProctoringService: Vision engines disabled.")

    # --- DISTRIBUTED STATE HELPERS ---
    
    def _get_sid_key(self, session_id: str, key: str) -> str:
        return f"{self._cache_prefix}{session_id}:{key}"

    async def _get_state(self, session_id: str, key: str, default: Any = None) -> Any:
        # ✅ TURBO: Check in-memory cache first
        if session_id in self._session_cache and key in self._session_cache[session_id]:
            return self._session_cache[session_id][key]
            
        full_key = self._get_sid_key(session_id, key)
        try:
            val = await self.cache.get(full_key)
            if val is not None:
                # Cache it locally for next time
                if session_id not in self._session_cache:
                    self._session_cache[session_id] = {}
                self._session_cache[session_id][key] = val
                return val
            return default
        except Exception as e:
            logger.debug(f"Cache miss/error for {key}: {e}")
            return default

    async def _set_state(self, session_id: str, key: str, value: Any, ttl: int = 3600):
        # ✅ TURBO: Update in-memory cache immediately (Synchronous feel)
        if session_id not in self._session_cache:
            self._session_cache[session_id] = {}
        self._session_cache[session_id][key] = value
        
        # Async background sync to Redis (fire and forget)
        async def sync_to_redis():
            try:
                full_key = self._get_sid_key(session_id, key)
                await self.cache.set(full_key, value, ttl=ttl)
            except Exception as e:
                logger.debug(f"Async Redis sync failed: {e}")
        
        asyncio.create_task(sync_to_redis())

    async def _del_state(self, session_id: str, key: str):
        # ✅ TURBO: Clear in-memory
        if session_id in self._session_cache and key in self._session_cache[session_id]:
            del self._session_cache[session_id][key]
            
        full_key = self._get_sid_key(session_id, key)
        async def sync_del_to_redis():
            try:
                await self.cache.delete(full_key)
            except Exception as e:
                logger.debug(f"Async Redis delete failed: {e}")
        
        asyncio.create_task(sync_del_to_redis())

    @property
    def violation_history(self):
        """Legacy access to violation history (NOT RECOMMENDED for new code)"""
        return {} # Should not be used directly anymore


    def validate_session_token(self, session_id: str) -> bool:

        """
        Validate session token (Stub implementation)
        In a real implementation, this would check against a session store or database.
        Since validation happens in SocketController, we can return True here.
        """
        return True

    async def verify_frame_integrity(self, frame_data: str, session_id: str) -> bool:
        """
        Verify frame integrity to detect loop/replay/fake cameras.
        Checks if frame is replay/fake by comparing hashes of consecutive frames.
        """
        try:
            if not frame_data: return False
            
            # 1. ROLLNG HASH CHECK: Detect frozen camera / static image
            last_hash = await self._get_state(session_id, 'last_frame_hash')
            hash_count = await self._get_state(session_id, 'identical_hash_count', 0)
            current_hash = hashlib.md5(frame_data.encode()).hexdigest()
            
            if last_hash == current_hash:
                hash_count += 1
                if hash_count >= 10: # ~10-20 seconds at 0.5-1 FPS
                    logger.warning(f"🚨 [INTEGRITY_VIOLATION][{session_id}] Frozen frame detected (10+ identical frames)")
                    # Reset count after warning to avoid spamming
                    await self._set_state(session_id, 'identical_hash_count', 0)
                    return False
                await self._set_state(session_id, 'identical_hash_count', hash_count)
            else:
                # Reset count on variations
                await self._set_state(session_id, 'identical_hash_count', 0)
                await self._set_state(session_id, 'last_frame_hash', current_hash, ttl=300)
                
            return True
        except Exception as e:
            logger.error(f"Integrity check failed: {e}")
            return True # Fail open to avoid disrupting the interview flow


    def cleanup_old_sessions(self):
        """
        ✅ PHASE 8: Memory Management
        Clean up sessions older than 1 hour to prevent memory leaks
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            
            # Clean violation history
            for session_id in list(self.violation_history.keys()):
                # This is a bit of a heuristic since we don't track update time per session in this dict
                # But we can assume if it's not in active_sessions (managed by SessionManager), it might be stale?
                # Actually, better to just rely on SessionManager to call cleanup_session_history
                pass
                
            # Clean violation start times
            cleaned_count = 0
            for session_id in list(self.violation_start_times.keys()):
                # Logic to determine if session is truly old would require a 'last_accessed' timestamp
                # For now, let's just clear completely empty ones or rely on external triggers
                if not self.violation_start_times[session_id]:
                    del self.violation_start_times[session_id]
                    cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"🧹 Cleaned up {cleaned_count} stale session records")
                
        except Exception as e:
            logger.error(f"Error during memory cleanup: {e}")

        
    async def check_violation_duration(
        self, 
        session_id: str, 
        violation_type: str,
        is_currently_detected: bool
    ) -> Dict[str, Any]:
        """
        Check if violation has persisted long enough to trigger a strike
        
        This prevents false positives from natural behavior:
        - Brief head turns while thinking (< 5s) = Focus warning only
        - Sustained violations (≥ threshold) = Strike
        
        Args:
            session_id: Session identifier
            violation_type: Type of violation detected
            is_currently_detected: Whether violation is currently happening
            
        Returns:
            {
                'should_trigger': bool,
                'duration': float,
                'violation_level': str  # 'FOCUS_WARNING', 'STRIKE', 'TERMINAL', or 'NONE'
            }
        """
        session_times = await self._get_state(session_id, 'violation_start_times', {})
        now = datetime.now(timezone.utc)
        
        # Determine threshold based on violation type
        if violation_type in self.INSTANT_VIOLATIONS:
            # Instant violations (extra person, no person)
            return {
                'should_trigger': is_currently_detected,
                'duration': 0,
                'violation_level': 'TERMINAL' if is_currently_detected else 'NONE'
            }
        
        threshold = (
            self.HEAD_POSE_DURATION_THRESHOLD 
            if violation_type in self.HEAD_POSE_VIOLATIONS 
            else self.OBJECT_DURATION_THRESHOLD
        )
        
        if is_currently_detected:
            # Violation is happening
            if violation_type not in session_times or session_times[violation_type] is None:
                # First detection - start timer
                session_times[violation_type] = now.isoformat()
                await self._set_state(session_id, 'violation_start_times', session_times)
                logger.debug(f"⏱️ Started timer for {violation_type}")
                return {
                    'should_trigger': False,
                    'duration': 0,
                    'violation_level': 'FOCUS_WARNING'
                }
            else:
                # Ongoing violation - check duration
                start_time = datetime.fromisoformat(session_times[violation_type])
                duration = (now - start_time).total_seconds()
                
                if duration >= threshold:
                    # Threshold exceeded - trigger strike and RESET timer to allow cooldown
                    logger.warning(
                        f"⚠️ SUSTAINED VIOLATION TRIGGERED: {violation_type} "
                        f"({duration:.1f}s ≥ {threshold}s threshold)"
                    )
                    # Reset timer so it must persist for ANOTHER full threshold period for next strike
                    session_times[violation_type] = None
                    await self._set_state(session_id, 'violation_start_times', session_times)
                    
                    return {
                        'should_trigger': True,
                        'duration': duration,
                        'violation_level': 'STRIKE'
                    }
                else:
                    # Still within grace period
                    logger.debug(
                        f"ℹ️ Focus warning: {violation_type} "
                        f"({duration:.1f}s / {threshold}s)"
                    )
                    return {
                        'should_trigger': False,
                        'duration': duration,
                        'violation_level': 'FOCUS_WARNING'
                    }
        else:
            # Violation stopped - reset timer
            if violation_type in session_times and session_times[violation_type] is not None:
                start_time = datetime.fromisoformat(session_times[violation_type])
                previous_duration = (now - start_time).total_seconds()
                session_times[violation_type] = None
                await self._set_state(session_id, 'violation_start_times', session_times)
                logger.debug(
                    f"✅ Reset timer for {violation_type} "
                    f"(was active for {previous_duration:.1f}s)"
                )
            
            return {
                'should_trigger': False,
                'duration': 0,
                'violation_level': 'NONE'
            }

    
    async def is_sustained_violation(self, session_id: str, violation_type: str) -> bool:
        """
        Check if violation is sustained across multiple consecutive frames
        
        This reduces false positives by only flagging violations that persist
        for CONSECUTIVE_FRAMES_REQUIRED frames.
        
        Args:
            session_id: Session identifier
            violation_type: Type of violation detected
            
        Returns:
            True if violation has been detected for required consecutive frames
        """
        history = await self._get_state(session_id, 'consecutive_history', {})
        
        if violation_type not in history:
            history[violation_type] = 1
        else:
            history[violation_type] += 1
        
        await self._set_state(session_id, 'consecutive_history', history)
        
        # Check if sustained
        is_sustained = history[violation_type] >= self.CONSECUTIVE_FRAMES_REQUIRED
        
        if is_sustained:
            logger.info(
                f"Sustained violation detected: {violation_type} "
                f"({history[violation_type]} consecutive frames)"
            )
            # ✅ RESET: Once sustained, reset counter to start a new cycle for the next warning/strike
            history[violation_type] = 0
            await self._set_state(session_id, 'consecutive_history', history)
        
        return is_sustained
    
    async def reset_violation_history(self, session_id: str, violation_type: str):
        """Reset violation history for a specific type"""
        history = await self._get_state(session_id, 'consecutive_history', {})
        if violation_type in history:
            # More forgiving reset: decrement instead of zeroing out immediately to handle YOLO flickering
            history[violation_type] = max(0, history[violation_type] - 1)
            await self._set_state(session_id, 'consecutive_history', history)
    
    async def cleanup_session_history(self, session_id: str):
        """Clean up violation history for a session"""
        if session_id in self._session_cache:
            del self._session_cache[session_id]
            
        await self._del_state(session_id, 'consecutive_history')
        await self._del_state(session_id, 'violation_start_times')
        await self._del_state(session_id, 'baseline')
        await self._del_state(session_id, 'frame_buffer')
        logger.debug(f"Cleaned up session data for {session_id}")


    async def calibrate_session(self, session_id: str, frame_data: str) -> Dict[str, Any]:
        """Calibration disabled"""
        return {'status': 'disabled', 'reason': 'Vision proctoring removed'}
    
    # process_frame previously here, now moved to stub above
    
    def get_violation_severity(self, violation_type: str) -> str:
        """Get severity level for violation type"""
        critical_violations = [
            self.VIOLATION_NO_PERSON,
            self.VIOLATION_EXTRA_PERSON,
            self.VIOLATION_PHONE
        ]
        return 'CRITICAL' if violation_type in critical_violations else 'HIGH'
    
    def should_terminate_interview(self, violations: List[Dict]) -> bool:
        """
        Determine if interview should be terminated based on violations
        
        Args:
            violations: List of violation dictionaries
            
        Returns:
            True if interview should be terminated
        """
        critical_count = sum(
            1 for v in violations 
            if v.get('severity') == 'CRITICAL'
        )
        return critical_count >= 3
    
    async def verify_frame_integrity(self, frame_data: str, session_id: str = None) -> bool:
        """
        ✅ PHASE 7: Frame Integrity & Anti-Replay
        Check if the frame is suspicious (e.g. static/replay)
        """
        if not session_id or not isinstance(frame_data, str):
            return True
            
        try:
            # Simple hash check to detect exact replays
            frame_hash = hashlib.md5(frame_data.encode()).hexdigest()
            
            # Get previous hashes
            history = await self._get_state(session_id, 'hash_history', [])
            
            if frame_hash in history:
                logger.warning(f"⚠️ REPLAY DETECTED: Frame hash already seen in session {session_id}")
                return False
                
            # Update history (keep last 10 hashes)
            history.append(frame_hash)
            if len(history) > 10:
                history.pop(0)
            
            await self._set_state(session_id, 'hash_history', history)
            return True
        except Exception as e:
            logger.error(f"Integrity check error: {e}")
            return True # Fail open to avoid blocking valid candidates
            
    def get_detection_stats(self, session_id: str = None) -> Dict[str, Any]:
        """
        ✅ ENTERPRISE: Get detection statistics for monitoring
        
        Args:
            session_id: Optional session ID for session-specific stats
            
        Returns:
            Dictionary with detection statistics
        """
        stats = {
            'total_frames_processed': self._detection_stats['total_frames'],
            'total_violations_detected': self._detection_stats['total_violations'],
            'model_loaded': self.model is not None,
            'gpu_enabled': str(next(self.model.parameters()).device) != 'cpu' if self.model else False,
            'thresholds': {},
            'consecutive_frames_required': self.CONSECUTIVE_FRAMES_REQUIRED,
            'duration_thresholds': {
                'head_pose': self.HEAD_POSE_DURATION_THRESHOLD,
                'objects': self.OBJECT_DURATION_THRESHOLD
            }
        }
        
        if session_id and session_id in self._detection_stats.get('detection_count', {}):
            stats['session_detections'] = self._detection_stats['detection_count'][session_id]
        
        return stats
        
    def process_frames_batch(self, frames: List[str], session_id: str) -> List[Dict[str, Any]]:
        """
        ✅ PHASE 8: Batch Processing
        Process multiple frames efficiently
        
        Args:
            frames: List of base64 encoded frame data
            session_id: Session identifier
            
        Returns:
            List of processing results
        """
        results = []
        for frame_data in frames:
            # For now, process sequentially 
            # (YOLOv8 can do batch inference, but we need decoded images first)
            # Future optimization: Decode all -> Batch Infer -> Process Results
            try:
                result = self.process_frame(frame_data, session_id)
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing frame in batch: {e}")
                results.append({'error': str(e), 'has_violations': False})
        return results
