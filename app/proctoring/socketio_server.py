"""
Socket.IO Server Configuration
Handles real-time notifications and Proctoring via WebSocket
"""
import socketio
from fastapi import FastAPI
from core.auth import decode_token_async
from utils import logger
import asyncio

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=[],  # Disabled to let FastAPI CORSMiddleware handle it natively
    logger=True,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25
)

# Wrap with ASGI app
# socketio_path="/" ensures the effective path is /socket.io (mount point)
# without this, it defaults to /socket.io internally causing /socket.io/socket.io/ doubling
socket_app = socketio.ASGIApp(sio, socketio_path="/")

controller = None

@sio.event
async def connect(sid, environ, auth):
    """Handle client connection"""
    global controller
    try:
        logger.info(f"Socket.IO connect attempt: sid={sid}, auth_keys={list(auth.keys()) if auth else None}")
            
        # Default behavior for notifications
        token = auth.get('token') if auth else None
        interview_id = auth.get('interview_id') if auth else None
        
        # If interview_id is present, it's a proctoring connection
        if interview_id and controller:
            success = await controller.handle_connect(sid, auth)
            logger.info(f"Proctor connect: interview_id={interview_id}, success={success}")
            if success:
                logger.info(f"✅ Socket.IO proctoring session connected: sid {sid} (Interview: {interview_id})")
            else:
                logger.warning(f"❌ Socket.IO proctoring connection REJECTED: sid {sid}")
            return success
        elif interview_id and not controller:
            logger.error(f"❌ Proctoring connection attempt but SocketController is NOT INITIALIZED (sid: {sid})")
            return False
            
        # Standard notification connection
        if not token:
            logger.warning(f"Socket.IO connection rejected - no token provided")
            return False
        
        user = await decode_token_async(token)
        if not user:
            logger.warning(f"Socket.IO connection rejected - invalid token")
            return False
        
        await sio.save_session(sid, {
            'user_id': user.id,
            'email': user.email,
            'is_recruiter': user.is_recruiter
        })
        
        await sio.enter_room(sid, f"user_{user.id}")
        logger.info(f"Socket.IO connected: {user.email} (sid: {sid})")
        
        await sio.emit('connected', {
            'message': 'Connected to notification server',
            'user_id': user.id
        }, to=sid)
        
        return True
    except Exception as e:
        logger.error(f"Socket.IO connection error: {e}")
        return False

@sio.event
async def disconnect(sid):
    global controller
    try:
        if controller:
            await controller.handle_disconnect(sid)
            
        session = await sio.get_session(sid)
        user_id = session.get('user_id') if session else 'unknown'
        logger.info(f"Socket.IO disconnected: user {user_id} (sid: {sid})")
    except:
        logger.info(f"Socket.IO disconnected: sid {sid}")

@sio.event
async def join_user_room(sid, data):
    try:
        session = await sio.get_session(sid)
        if session:
            user_id = session.get('user_id')
            await sio.enter_room(sid, f"user_{user_id}")
            logger.info(f"User {user_id} joined room user_{user_id}")
            await sio.emit('room_joined', {'room': f"user_{user_id}"}, to=sid)
    except Exception as e:
        logger.error(f"Error joining room: {e}")

@sio.event
async def join_interview(sid, data):
    global controller
    if controller:
        await controller.handle_join_interview(sid, data)

@sio.event
async def start_interview(sid, data):
    global controller
    if controller:
        await controller.handle_start_interview(sid, data)


@sio.event
async def audio_activity(sid, data):
    global controller
    if controller:
        await controller.handle_audio_activity(sid, data)

@sio.event
async def submit_answer(sid, data):
    global controller
    if controller:
        await controller.handle_submit_answer(sid, data)


@sio.event
async def stop_proctoring(sid, data):
    global controller
    if controller:
        # We can implement a handle_stop_proctoring later if needed
        await controller.handle_disconnect(sid)

async def send_notification_to_user(user_id: str, notification: dict):
    """Send a real-time notification to a specific user via Socket.IO"""
    try:
        # Emit to the user's private room
        await sio.emit('notification', notification, room=f"user_{user_id}")
        logger.info(f"Socket.IO notification sent to user_{user_id}")
    except Exception as e:
        logger.error(f"Failed to send Socket.IO notification: {e}")

def mount_socketio(app: FastAPI):
    """Mount Socket.IO to FastAPI app"""
    # The SocketController will be initialized natively during the application lifespan
    # inside app/main.py. This prevents sync/async lockups during startup.
    app.mount('/socket.io', socket_app)
    logger.info("Socket.IO mounted at /socket.io")
    return sio
