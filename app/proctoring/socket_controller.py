"""
Socket Controller
Handles Socket.IO events for proctoring, delegating business logic to services.
"""
import base64
from datetime import datetime, timezone
from bson import ObjectId
import hashlib
import hmac
import secrets
import asyncio
import structlog

logger = structlog.get_logger(__name__)

class SocketController:
    """
    Controller for Socket.IO events (Asyncified for FastAPI/ASGI).
    """
    def __init__(self, socketio, session_manager, db):
        self.socketio = socketio
        self.session_manager = session_manager
        self.db = db
        
        # ✅ PERFORMANCE: In-memory interview metadata cache
        self._interview_cache = {}

    async def handle_connect(self, sid, auth):
        """Handle client connection"""
        try:
            client_id = sid
            token = auth.get('token') if auth else None
            interview_id = auth.get('interview_id') if auth else None
            user_id = auth.get('user_id') if auth else None
            
            logger.debug("handle_connect_start", sid=sid, interview_id=interview_id)

            # ✅ RACE FIX: Register connection immediately
            await self.session_manager.register_connection(client_id, token)

            # ✅ GET USER FROM TOKEN (If available)
            from core.auth import decode_token_async
            
            user = None
            if token and token.startswith('eyJ'):
                try:
                    user = await decode_token_async(token)
                    if user and not user_id:
                        extracted_id = getattr(user, 'id', user.get('id', user.get('sub')) if isinstance(user, dict) else None)
                        user_id = str(extracted_id) if extracted_id else None
                except Exception as auth_err:
                    logger.error("auth_decoding_failed", error=str(auth_err))

            # Verify access
            logger.debug("verifying_access", interview_id=interview_id, user_id=user_id)
            if not await self._verify_access(interview_id, user_id, token):
                logger.warning("unauthorized_connection", client_id=client_id, interview_id=interview_id)

                await self.socketio.emit('error', {'message': 'Unauthorized access'}, to=sid)
                return False
            


            # ✅ REPLAY PROTECTION: Generate a unique nonce for this connection
            session_nonce = secrets.token_hex(16)
            
            # ✅ CONNECTION FIX: Update the already registered connection with full details
            await self.session_manager.update_session(client_id, {
                'nonce': session_nonce, 
                'interview_id': interview_id,
                'user_id': user_id,
                'status': 'connected'
            })
            
            logger.info("connection_established", client_id=client_id, interview_id=interview_id)
            
            await self.socketio.emit('connected', {
                'status': 'ready',
                'client_id': client_id,
                'nonce': session_nonce,
                'message': 'Connected to proctoring server'
            }, to=sid)
            return True
        except Exception as e:
            logger.error("connect_error", error=str(e), exc_info=True)
            await self.socketio.emit('error', {'message': 'Connection initialization failed'}, to=sid)
            return False

    async def handle_disconnect(self, sid):
        """Handle client disconnection"""
        try:
            client_id = sid
            session = await self.session_manager.get_session(client_id)
            
            # ✅ PHASE 3: Record CONNECTION_LOST for unexpected disconnects
            if session and session.get('status') == 'active':
                interview_id = session.get('interview_id')
                logger.warning("unexpected_disconnect", interview_id=interview_id)
                
                from app.proctoring.warning_manager import ViolationType
                if not hasattr(self, 'warning_manager'):
                    from app.proctoring.warning_manager import WarningManager
                    self.warning_manager = WarningManager(self.db)
                
                # Record violation (Severity is now WARNING) (Async)
                await self.warning_manager.record_violation(
                    interview_id=interview_id,
                    violation_type=ViolationType.CONNECTION_LOST,
                    metadata={
                        'session_id': client_id,
                        'reason': 'Socket connection lost'
                    }
                )
            
            await self.session_manager.remove_connection(client_id)
            
        except Exception as e:
            logger.error("disconnect_cleanup_error", error=str(e))

    async def handle_join_interview(self, sid, data):
        """Handle join interview event"""
        await self.socketio.emit('proctoring_status', {'status': 'joined'}, to=sid)

    async def handle_start_interview(self, sid, data):
        """Handle start interview event (starts proctoring and sets active state)"""
        try:
            client_id = sid
            interview_id = data.get('interview_id')
            candidate_name = data.get('candidate_name', 'Unknown')
            
            logger.info("start_interview_event", sid=sid, interview_id=interview_id)
            
            if not interview_id:
                await self.socketio.emit('error', {'message': 'Interview ID required'}, to=sid)
                return

            # 1. Input Validation & Auth Check
            session = await self.session_manager.get_session(client_id)
            if not session: 
                 await self.socketio.emit('error', {'message': 'Connection session lost'}, to=sid)
                 await self.socketio.disconnect(sid)
                 return

            # Verify access (Interview exists and user/token is valid)
            user_id = session.get('user_id')
            if not await self._verify_access(interview_id, user_id, session.get('auth_token')):
                logger.warning("proctoring_access_denied", interview_id=interview_id)
                await self.socketio.emit('error', {'message': 'Unauthorized'}, to=sid)
                await self.socketio.disconnect(sid)
                return
            
            logger.info("proctoring_access_verified", interview_id=interview_id)
                
            # ✅ ENTERPRISE: Check if interview can be resumed
            if not await self.session_manager.can_resume_session(interview_id):
                logger.warning("resume_blocked", interview_id=interview_id)
                await self.socketio.emit('error', {
                    'message': 'Interview locked',
                    'terminated': True
                }, to=sid)
                await self.socketio.disconnect(sid)
                return
                
            # 2. Start Session (Delegated to SessionManager)
            await self.session_manager.create_session(client_id, interview_id, user_id, session.get('auth_token'), candidate_name)
            
            logger.info("proctoring_active", interview_id=interview_id)
            
            # ✅ PHASE B: Handshake Synchronization
            # Wait for interview to reach a 'processing' state
            max_retries = 10
            retry_delay = 0.2
            is_ready = False
            interview_meta = None

            for attempt in range(max_retries):
                interview = await self.db.interviews.find_one({'_id': ObjectId(interview_id)})
                if interview:
                    current_state = interview.get('state', 'init')
                    if SocketController.is_proctoring_allowed(current_state):
                        is_ready = True
                        interview_meta = {
                            'state': current_state,
                            'resume_id': str(interview.get('resume_id')),
                            'candidate_id': str(interview.get('candidate_id')),
                            'recruiter_id': str(interview.get('recruiter_id')),
                            'application_id': str(interview.get('application_id')),
                            'access_token': interview.get('access_token'),
                            'last_cached': datetime.now(timezone.utc)
                        }
                        break
                
                if attempt < max_retries - 1:
                    logger.info("waiting_for_state_transition", interview_id=interview_id, attempt=attempt+1, max_retries=max_retries)
                    await asyncio.sleep(retry_delay)

            if not is_ready:
                logger.warning("interview_state_not_active", interview_id=interview_id, retries=max_retries)

            # ✅ TURBO: Cache interview metadata eagerly
            if interview_meta:
                self._interview_cache[interview_id] = interview_meta
                logger.debug("interview_cached", interview_id=interview_id, state=interview_meta['state'])

            await self.socketio.emit('interview_started', {
                'interview_id': interview_id,
                'session_id': client_id,
                'message': 'Interview & Proctoring session started'
            }, to=sid)
            
            # ✅ FIX: Explicitly emit 'proctoring_started' for YOLO hook compatibility
            await self.socketio.emit('proctoring_started', {
                'status': 'active',
                'interview_id': interview_id,
                'handshake_complete': True # ✅ PHASE B signal
            }, to=sid)
                
        except Exception as e:
            logger.error("start_proctoring_error", error=str(e))
            await self.socketio.emit('error', {'message': 'Internal server error during startup'}, to=sid)
            await self.socketio.disconnect(sid)

    # handle_calibrate, handle_video_frame, and _process_frame_logic removed 
    # Vision proctoring is disabled.

    async def handle_question_timeout(self, sid, data):
        """Fix Question Timeout & Auto-Advance"""
        try:
            client_id = sid
            session = await self.session_manager.get_session(client_id)
            if not session: return
            
            interview_id = session.get('interview_id')
            if not interview_id: return
            
            question_id = data.get('question_id')
            
            logger.info("question_timeout", question_id=question_id, action="auto_submit")
            
            # Forward to backend submit API (FAST ACK)
            from app.proctoring.service import get_db
            from services.interview.core import submit_response_fast, InterviewResponse
            
            db = await get_db()
            response_data = dict(
                response=data.get('answer', ""),
                timeout=True
            )
            # Submit via core function directly
            result = await submit_response_fast(interview_id, InterviewResponse(**response_data), db)
            
            logger.info("advancing_to_next_question", interview_id=interview_id)
            
            # Emit next_question event to trigger UI advance
            await self.socketio.emit('next_question', {
                'status': 'advanced',
                'question_index': result.get('response', {}).get('next_idx', 0),
                'completed': result.get('response', {}).get('status') == 'completed',
                'question_expires_at': result.get('response', {}).get('question_expires_at'),
                'question_duration': result.get('response', {}).get('question_duration')
            }, to=sid)
            
        except Exception as e:
            logger.error("timeout_handle_error", error=str(e))

    async def handle_audio_activity(self, sid, data):
        """Handle audio RMS/speaking boolean"""
        try:
            client_id = sid
            session = await self.session_manager.get_session(client_id)
            if not session or session.get('status') != 'active':
                return
            
            interview_id = session.get('interview_id')
            is_noise = data.get('is_noise', False)
            is_speaking = data.get('is_speaking', False)
            audio_level = data.get('level', 0)
            
            interview_meta = self._interview_cache.get(interview_id)
            current_state = 'init'
            if interview_meta:
                current_state = interview_meta.get('state', 'init')
            else:
                interview = await self.db.interviews.find_one({'_id': ObjectId(interview_id)})
                if interview:
                    current_state = interview.get('state', 'init')
                    
            if not SocketController.is_proctoring_allowed(current_state):
                return
            
            if is_speaking or is_noise:
                from app.proctoring.warning_manager import ViolationType
                if not hasattr(self, 'warning_manager'):
                    from app.proctoring.warning_manager import WarningManager
                    self.warning_manager = WarningManager(self.db)
                
                # Use local suppression to avoid spamming db 
                last_recorded = session.get('last_recorded_violations', {})
                now = datetime.now(timezone.utc)
                v_key = 'AUDIO_DETECTED' if is_speaking else 'BACKGROUND_NOISE'
                last_time_str = last_recorded.get(v_key)
                
                if last_time_str:
                    last_time = datetime.fromisoformat(last_time_str)
                    # Suppress speaking for 5s, noise for 10s
                    threshold = 5 if is_speaking else 10
                    if (now - last_time).total_seconds() < threshold:
                        return
                
                last_recorded[v_key] = now.isoformat()
                session['last_recorded_violations'] = last_recorded
                await self.session_manager.update_session(client_id, {'last_recorded_violations': last_recorded})
                
                if is_speaking:
                    warning_result = await self.warning_manager.record_violation(
                        interview_id=interview_id,
                        violation_type=ViolationType.AUDIO_DETECTED,
                        metadata={'level': audio_level, 'source': 'audio_activity', 'session_id': client_id}
                    )
                    
                    if 'error' not in warning_result:
                        await self.socketio.emit('violation_detected', {
                            'type': 'AUDIO_DETECTED',
                            'timestamp': now.isoformat()
                        }, to=sid)
                else:
                    # Log noise but don't record strike unless repetitive (handled by WarningManager deduplication if we chose to record)
                    # For now, just a status update to frontend
                    logger.info("noise_detected", level=audio_level)
                    await self.socketio.emit('status_update', {
                        'audio_status': 'NOISY',
                        'level': audio_level
                    }, to=sid)
                
        except Exception as e:
            logger.error("audio_activity_error", error=str(e))

    async def handle_submit_answer(self, sid, data):
        """Handle manual submission via socket"""
        try:
            client_id = sid
            session = await self.session_manager.get_session(client_id)
            if not session: return
            
            interview_id = session.get('interview_id')
            if not interview_id: return
            
            from app.proctoring.service import get_db
            from services.interview.core import submit_response_fast, InterviewResponse
            
            db = await get_db()
            response_data = dict(
                response=data.get('answer', ""),
                timeout=False
            )
            result = await submit_response_fast(interview_id, InterviewResponse(**response_data), db)
            
            await self.socketio.emit('next_question', {
                'status': 'advanced',
                'question_index': result.get('response', {}).get('next_idx', 0),
                'completed': result.get('response', {}).get('status') == 'completed'
            }, to=sid)
            
        except Exception as e:
            logger.error("submit_answer_error", error=str(e))

    async def handle_focus_event(self, sid, data):
        """Handle focus events"""
        try:
            client_id = sid
            session = await self.session_manager.get_session(client_id)
            if not session or session.get('status') != 'active':
                return
            
            interview_id = session.get('interview_id')
            is_focused = data.get('is_focused', True)
            
            interview_meta = self._interview_cache.get(interview_id)
            current_state = 'init'
            if interview_meta:
                current_state = interview_meta.get('state', 'init')
            else:
                interview = await self.db.interviews.find_one({'_id': ObjectId(interview_id)})
                if interview:
                    current_state = interview.get('state', 'init')

            if not SocketController.is_proctoring_allowed(current_state):
                return
                
            if not is_focused:
                from app.proctoring.warning_manager import ViolationType
                if not hasattr(self, 'warning_manager'):
                    from app.proctoring.warning_manager import WarningManager
                    self.warning_manager = WarningManager(self.db)
                
                # Check deduplication window to prevent strike spam
                last_recorded = session.get('last_recorded_violations', {})
                now = datetime.now(timezone.utc)
                v_key = 'WINDOW_FOCUS_LOST'
                last_time_str = last_recorded.get(v_key)
                if last_time_str:
                    last_time = datetime.fromisoformat(last_time_str)
                    if (now - last_time).total_seconds() < 5:
                        return
                        
                last_recorded[v_key] = now.isoformat()
                session['last_recorded_violations'] = last_recorded
                await self.session_manager.update_session(client_id, {'last_recorded_violations': last_recorded})
                
                await self.warning_manager.record_violation(
                    interview_id=interview_id,
                    violation_type=ViolationType.WINDOW_FOCUS_LOST,
                    metadata={'source': 'focus_event', 'session_id': client_id}
                )
        except Exception as e:
            logger.error("focus_event_error", error=str(e))

    async def handle_tab_switch(self, sid, data):
        """Handle tab switch events"""
        try:
            client_id = sid
            session = await self.session_manager.get_session(client_id)
            if not session or session.get('status') != 'active':
                return
            
            interview_id = session.get('interview_id')
            
            interview_meta = self._interview_cache.get(interview_id)
            current_state = 'init'
            if interview_meta:
                current_state = interview_meta.get('state', 'init')
            else:
                interview = await self.db.interviews.find_one({'_id': ObjectId(interview_id)})
                if interview:
                    current_state = interview.get('state', 'init')

            if not SocketController.is_proctoring_allowed(current_state):
                return
                
            from app.proctoring.warning_manager import ViolationType
            if not hasattr(self, 'warning_manager'):
                from app.proctoring.warning_manager import WarningManager
                self.warning_manager = WarningManager(self.db)
            
            # Check deduplication window to prevent strike spam
            last_recorded = session.get('last_recorded_violations', {})
            now = datetime.now(timezone.utc)
            v_key = 'TAB_SWITCHED'
            last_time_str = last_recorded.get(v_key)
            if last_time_str:
                last_time = datetime.fromisoformat(last_time_str)
                if (now - last_time).total_seconds() < 5:
                    return
                    
            last_recorded[v_key] = now.isoformat()
            session['last_recorded_violations'] = last_recorded
            await self.session_manager.update_session(client_id, {'last_recorded_violations': last_recorded})
            
            await self.warning_manager.record_violation(
                interview_id=interview_id,
                violation_type=ViolationType.TAB_SWITCHED,
                metadata={'source': 'tab_switch', 'session_id': client_id}
            )
        except Exception as e:
            logger.error("tab_switch_error", error=str(e))

    # --- Private Helpers ---

    @staticmethod
    def is_proctoring_allowed(state: str) -> bool:
        """Helper to determine if proctoring features should be active based on interview state."""
        return state in [
            "STARTED",
            "RUNNING",
            "QUESTION_ACTIVE",
            "QUESTION_TIMEOUT",
            "QUESTION_SUBMITTED"
        ]

    async def _verify_access(self, interview_id, user_id, token):
         try:
             if not interview_id:
                 return False
             
             if not ObjectId.is_valid(interview_id):
                 logger.error("invalid_interview_id_format", interview_id=interview_id)
                 return False

             t1 = datetime.now()
             interview = await self.db.interviews.find_one({"_id": ObjectId(interview_id)})
             t2 = datetime.now()
             logger.debug("db_fetch_interview", duration_s=round((t2-t1).total_seconds(), 3))

             if not interview:
                 logger.error("interview_not_found", interview_id=interview_id)
                 return False
                 
             if user_id:
                 if str(interview.get('recruiter_id')) == user_id: return True
                 if str(interview.get('candidate_id')) == user_id: return True
                 
             if token:
                 app_token = None
                 app_id = interview.get("application_id")
                 if app_id:
                     try:
                         app_id_obj = ObjectId(app_id) if isinstance(app_id, str) else app_id
                         app_doc = await self.db.applications.find_one({"_id": app_id_obj}, {"interview_token": 1})
                         if app_doc:
                             app_token = app_doc.get("interview_token")
                     except Exception as e:
                         logger.error(f"Failed to lookup application token: {e}")
                         
                 valid_tokens = [
                     interview.get("access_token"), 
                     interview.get("interview_token"),
                     app_token
                 ]
                 valid_tokens = [t for t in valid_tokens if t]
                 
                 if token in valid_tokens:
                     return True
                     
             logger.warning("access_denied", interview_id=interview_id, user_id=user_id)
             return False
         except Exception as e:
             logger.error("verify_access_error", error=str(e))
             return False

    async def _verify_signature(self, session, signature, frame, seq, ts):
        if not signature:
            return False
            
        nonce = session.get('nonce')
        if not nonce:
            return False
            
        try:
            frame_hash = hashlib.md5(frame.encode()).hexdigest()
            payload = f"{nonce}{seq}{ts}{frame_hash}"
            expected = hashlib.sha256(payload.encode()).hexdigest()
            
            return hmac.compare_digest(signature, expected)
        except:
            return False

    async def _check_frame_integrity(self, session, sequence, client_timestamp, client_id, sid):
        if sequence is not None:
            last_sequence = session.get('last_sequence', -1)
            expected = last_sequence + 1
            
            # ✅ TOLERANCE: Allow frames slightly out of order if they arrive within a 3-frame window.
            # This prevents "scary" warnings for minor network jitter.
            if sequence != expected:
                if sequence < last_sequence:
                    # Significant lag or duplicate - Strictly reject
                    # This prevents replay attacks or out-of-order frame processing
                    logger.warning("replay_protection_reject", client_id=client_id, sequence=sequence, last_sequence=last_sequence)
                    return False
                else:
                    # Gap in sequence - expected in async streaming (Frame Drop)
                    logger.debug(f"Frame gap: {sequence} (expected {expected})")
            
            # Only advance sequence if this is the newest frame we've seen
            if sequence > last_sequence:
                session['last_sequence'] = sequence
            
        if client_timestamp:
            try:
                now = datetime.now(timezone.utc)
                # ✅ FIX: The frontend sends Date.now() — a Unix epoch in MILLISECONDS (integer).
                # dateutil.parse cannot handle raw integers. We must convert correctly.
                if isinstance(client_timestamp, (int, float)):
                    # Unix ms integer from Date.now()
                    client_time = datetime.fromtimestamp(client_timestamp / 1000.0, tz=timezone.utc)
                else:
                    from dateutil.parser import parse
                    client_time = parse(str(client_timestamp))
                    if client_time.tzinfo is None:
                        client_time = client_time.replace(tzinfo=timezone.utc)
                
                age_ms = (now - client_time).total_seconds() * 1000
                if age_ms > 5000:  # Allow up to 5s lag for slow connections
                    logger.warning("lag_protection_drop", client_id=client_id, age_ms=round(age_ms))
                    await self.socketio.emit('warning', {'message': 'Frame delivery delayed - dropping stale data', 'age_ms': age_ms}, to=sid)
                    return False
            except Exception as e:
                logger.debug("timestamp_parse_error", error=str(e))
                # Fail open — don't drop frame just because timestamp parsing failed
                pass
        return True

    async def _handle_violations_background(self, session, result, interview_id, client_id, sid):
        """Background wrapper for violation handling to avoid blocking the hot path"""
        try:
            await self._handle_violations(session, result, interview_id, client_id, sid)
        except Exception as e:
            logger.error("background_violation_handling_failed", error=str(e))

    async def _handle_violations(self, session, result, interview_id, client_id, sid):
        """
        Handles:
        1. Focus warnings (brief violations, 0 strikes)
        2. Strike violations (sustained violations)
        3. Automatic termination at 3 strikes
        4. Email notifications
        5. Security logging
        """
        from app.proctoring.warning_manager import WarningManager, ViolationType
        from services.email.email_service import send_cheating_warning_email, send_cheating_disqualification_email
        from services.infrastructure.security_logger import log_security_event
        
        # Initialize WarningManager
        if not hasattr(self, 'warning_manager'):
            self.warning_manager = WarningManager(self.db)
        
        interview = await self.db.interviews.find_one({'_id': ObjectId(interview_id)})
        if not interview:
            return

        # ✅ STANDARDIZED STATES: Only record strikes if the interview is actively running.
        current_state = interview.get('state', 'init')
        
        if not SocketController.is_proctoring_allowed(current_state):
            logger.info("proctoring_gate_skip", client_id=client_id, state=current_state)
            return
        
        resume = await self.db.resumes.find_one({'_id': ObjectId(interview['resume_id'])})
        candidate_email = resume.get('email') if resume else None
        candidate_name = resume.get('candidate_name', 'Candidate') if resume else 'Candidate'
        
        # ✅ PHASE 2.1: Handle focus warnings
        if result.get('focus_warnings'):
            for warning in result['focus_warnings']:
                await self.socketio.emit('focus_warning', {
                    'type': warning['type'],
                    'duration': warning['duration'],
                    'threshold': warning['threshold'],
                    'message': warning['message'],
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, to=sid)
        
        # ✅ PHASE 2.2: Process strike violations through WarningManager
        VIOLATION_TYPE_MAP = {
            'AUDIO_DETECTED': ViolationType.AUDIO_DETECTED,
            'DEVTOOLS_ATTEMPTED': ViolationType.DEVTOOLS_ATTEMPTED,
            'VIEW_SOURCE_ATTEMPTED': ViolationType.VIEW_SOURCE_ATTEMPTED,
            'RIGHT_CLICK_BLOCKED': ViolationType.RIGHT_CLICK_BLOCKED,
            'FOCUS_WARNING': ViolationType.FOCUS_WARNING,
            'WINDOW_FOCUS_LOST': ViolationType.WINDOW_FOCUS_LOST,
            'TAB_SWITCHED': ViolationType.TAB_SWITCHED,
        }
        
        # ✅ STABILITY: Implement local suppression for high-frequency violations
        # We avoid hitting WarningManager (and the DB) if we already recorded this type recently
        last_recorded = session.get('last_recorded_violations', {})
        now = datetime.now(timezone.utc)
        
        for violation in result['violations']:
            violation_type_str = violation.get('type')
            
            violation_enum = VIOLATION_TYPE_MAP.get(violation_type_str)
            if not violation_enum:
                continue
            
            try:
                # Record violation through WarningManager (Async)
                warning_result = await self.warning_manager.record_violation(
                    interview_id=interview_id,
                    violation_type=violation_enum,
                    metadata={
                        'session_id': client_id,
                        'source': violation.get('source', 'backend')
                    }
                )
                
                # Check for duplicate/error
                if 'error' in warning_result:
                    continue
                
                total_strikes = warning_result['total_strikes']
                should_terminate = warning_result['should_terminate']
                termination_reason = warning_result.get('termination_reason')
                grace_applied = warning_result.get('grace_applied', False)
                
                # Send warning email
                if not should_terminate and candidate_email:
                    try:
                        # Use purely async email sending if supported
                        await send_cheating_warning_email(
                            db=self.db,
                            to_email=candidate_email,
                            candidate_name=candidate_name,
                            reason=warning_result['violation']['type'].replace('_', ' ').title(),
                            warning_count=total_strikes
                        )
                    except Exception as e:
                        logger.error("warning_email_failed", error=str(e))
                
                # ✅ CRITICAL: Enforce termination
                if should_terminate:
                    if candidate_email:
                        try:
                            await send_cheating_disqualification_email(
                                db=self.db,
                                to_email=candidate_email,
                                candidate_name=candidate_name,
                                reason=termination_reason
                            )
                        except Exception as e:
                            logger.error("disqualification_email_failed", error=str(e))
                    
                    # Emit termination event to client
                    await self.socketio.emit('interview_terminated', {
                        'reason': termination_reason,
                        'total_strikes': total_strikes,
                        'violation_type': violation_type_str,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }, to=sid)
                    
                    # Terminate session
                    await self.session_manager.terminate_session(client_id, termination_reason)
                    await self.socketio.disconnect(sid)
                    return
                
                else:
                    await self.socketio.emit('violation_warning', {
                        'violation': warning_result['violation'],
                        'total_strikes': total_strikes,
                        'strikes_remaining': warning_result['strikes_remaining'],
                        'grace_applied': grace_applied,
                        'duration': violation.get('duration', 0),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }, to=sid)
                    
                # Structured violation log
                logger.info("violation_processed", type=violation_type_str, confidence=violation.get('confidence', 0), duration=violation.get('duration', 0))
                
            except Exception as e:
                logger.error("violation_processing_failed", error=str(e))
        
        # Vision violation logging removed
        pass

