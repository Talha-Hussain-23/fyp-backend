"""
SmartHiring API - Main Application
Production-ready FastAPI server optimized for Railway deployment.
Key design: lifespan does ONLY lightweight init (DB connect + cache),
then yields immediately so the server binds the port within seconds.
All heavy background services launch AFTER the server is ready.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
import os
import sys
import asyncio
import structlog

# Core Modules
from core.config import settings
from utils.console_logger import rich_logger
from core.logging_service import logger, init_logging_service
from utils.exceptions import AppException
from middleware.error_handler import global_exception_handler
from middleware.security import SecurityHeadersMiddleware
from core.request_id_middleware import RequestIDMiddleware

# Routes
from routes import (
    auth_router, jobs_router, candidates_router, interviews_router,
    analytics_router, applications_router, screening_router,
    user_router, notifications_router, recruiter_router,
    reclaim_router, email_router, feedback_router
)
from routes.violations import router as violations_router
from routes.enhanced_analytics import router as enhanced_analytics_router

# Background task references for clean shutdown
_background_tasks: list[asyncio.Task] = []


def _register_task(task: asyncio.Task) -> asyncio.Task:
    """Track a background task for graceful shutdown."""
    _background_tasks.append(task)
    return task


# ──────────────────────────────────────────────────────────────
# Background Services (launched AFTER server is ready)
# ──────────────────────────────────────────────────────────────
async def _bootstrap_background_services(app: FastAPI):
    """
    Launches all heavy background services AFTER the server is already
    accepting connections. This ensures Railway's health check passes
    before any long-running initialization begins.
    """
    # Small delay to guarantee the event loop is fully serving requests
    await asyncio.sleep(0.5)
    logger.info("background_bootstrap_started")

    # ── Database Optimization (non-blocking) ─────────────────
    try:
        from services.infrastructure.db_optimizer import create_performance_indexes, optimize_database_connection
        from utils.db import get_db

        async def background_db_init():
            try:
                logger.info("optimizing_database_async")
                db = await get_db()
                await create_performance_indexes(db)
                await optimize_database_connection(db)
                logger.info("database_optimization_complete")
            except Exception as e:
                logger.error("db_optimization_failed", error=str(e))

        _register_task(asyncio.create_task(background_db_init()))
    except Exception as e:
        logger.error("db_optimizer_import_failed", error=str(e))

    # ── Proctoring Services ──────────────────────────────────
    try:
        from utils.db import get_db
        db = await get_db()

        from app.proctoring.session_manager import SessionManager
        session_manager = SessionManager(db)
        app.state.session_manager = session_manager

        from app.proctoring.socket_controller import SocketController
        import app.proctoring.socketio_server as socketio_server

        socketio_server.controller = SocketController(
            socketio_server.sio,
            session_manager,
            db
        )
        logger.info("proctoring_controller_initialized")

        # Session watchdog — garbage-collects stale sessions
        async def session_watchdog():
            logger.info("session_watchdog_started")
            while True:
                try:
                    await asyncio.sleep(300)
                    removed = await session_manager.garbage_collect_stale_sessions(max_idle_minutes=10)
                    if removed > 0:
                        logger.info("watchdog_cleanup", removed=removed)
                except asyncio.CancelledError:
                    logger.info("session_watchdog_stopped")
                    break
                except Exception as e:
                    logger.error("watchdog_error", error=str(e))

        app.state.watchdog_task = _register_task(asyncio.create_task(session_watchdog()))

        # Timer watchdog — handles per-question timeouts
        async def timer_watchdog():
            logger.info("timer_watchdog_started")
            from services.interview.interview_timer import InterviewTimer
            timer_service = InterviewTimer(db)
            while True:
                try:
                    await asyncio.sleep(1)
                    if getattr(socketio_server, 'controller', None):
                        await timer_service.process_question_timeouts(socketio_server.controller)
                except asyncio.CancelledError:
                    logger.info("timer_watchdog_stopped")
                    break
                except Exception as e:
                    logger.error("timer_watchdog_error", error=str(e))

        app.state.timer_task = _register_task(asyncio.create_task(timer_watchdog()))
        rich_logger.print_status("Proctoring Services Started", status="success")
    except Exception as e:
        logger.error("proctoring_init_failed", error=str(e))

    # ── Background Scheduler ─────────────────────────────────
    async def run_scheduler():
        from utils.db import get_db
        from services.automation.job_automation import process_scheduled_jobs, check_and_process_deadlines
        logger.info("scheduler_started")
        while True:
            try:
                task_db = await get_db()
                await process_scheduled_jobs(task_db)
                await check_and_process_deadlines(task_db)
            except asyncio.CancelledError:
                logger.info("scheduler_stopped")
                break
            except Exception as e:
                logger.error("scheduler_error", error=str(e))
            await asyncio.sleep(60)

    _register_task(asyncio.create_task(run_scheduler()))
    rich_logger.print_status("Scheduler Running", status="success", details=["Interval: 60s", "Mode: Async"])

    # ── Email Worker ─────────────────────────────────────────
    try:
        from services.email.email_worker import email_worker
        _register_task(asyncio.create_task(email_worker.start()))
        logger.info("email_worker_started")
        rich_logger.print_status("Email Worker Started", status="success", details=["Status: Listening"])
    except Exception as e:
        logger.error("email_worker_start_failed", error=str(e))

    logger.info("background_bootstrap_complete")


# ──────────────────────────────────────────────────────────────
# Lifespan: LIGHTWEIGHT startup / graceful shutdown
# ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Railway-safe lifespan handler.
    ONLY performs critical, fast initialization:
      1. DB connection (Motor async — non-blocking)
      2. Cache init (in-memory — instant)
      3. Event handler registration
    Then yields immediately so Uvicorn binds the port.
    All heavy background work is scheduled via asyncio.create_task
    and runs AFTER the server is accepting connections.
    """
    # Print Startup Banner
    rich_logger.print_banner(
        title="SMARTHIRING API SERVER",
        subtitle=f"v{settings.APP_VERSION}",
        info={
            "Environment": settings.ENVIRONMENT,
            "Host": "0.0.0.0",
            "Port": os.environ.get("PORT", str(settings.PORT)),
            "Database": settings.DATABASE_NAME,
            "Python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        },
        emoji=">"
    )

    logger.info("startup_initiated", version=settings.APP_VERSION, env=settings.ENVIRONMENT)
    rich_logger.print_section("INITIALIZING CORE SERVICES", ">")

    # ── 1. Database Connection (lightweight — just connect, no heavy ops) ──
    try:
        from utils.db import get_db, get_connection_manager
        from services.infrastructure.event_handlers import register_event_handlers

        register_event_handlers()

        manager = await get_connection_manager()
        db = manager.get_database()

        init_logging_service(db)
        rich_logger.print_status("Database Connected", status="success", details=["Driver: Motor/Async"])
    except Exception as e:
        logger.critical("startup_failed_database", error=str(e))
        raise

    # ── 2. Cache (instant — in-memory) ───────────────────────
    try:
        from core.cache import get_cache_service
        get_cache_service()
        rich_logger.print_status("Cache: In-Memory Initialized", status="success")
    except Exception as e:
        logger.error("cache_init_failed", error=str(e))

    # Background services are launched via @app.on_event("startup")
    # AFTER the server has fully bound the port — see startup_background_services()

    # ── SERVER IS READY — yield to Uvicorn ───────────────────
    port = int(os.environ.get("PORT", settings.PORT))
    logger.info("application_ready", host="0.0.0.0", port=port, message="Server is accepting connections")
    rich_logger.print_section("SERVER READY", "✅")
    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("shutdown_initiated")

    # Cancel all background tasks gracefully
    for task in _background_tasks:
        if not task.done():
            task.cancel()

    # Wait for tasks to finish cancellation (up to 5s)
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    # Stop email worker
    try:
        from services.email.email_worker import email_worker
        await email_worker.stop()
    except Exception as e:
        logger.error("email_worker_stop_failed", error=str(e))

    # Close database connections
    try:
        from utils.db import get_connection_manager
        manager = await get_connection_manager()
        manager.close()
    except Exception as e:
        logger.error("db_close_failed", error=str(e))

    logger.info("shutdown_complete")


# ──────────────────────────────────────────────────────────────
# Application Factory
# ──────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# ── Middleware Stack ─────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "https://fyp-frontend-pi-tan.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600
)

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from core.rate_limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
logger.info("rate_limiting_enabled")
rich_logger.print_status("Rate Limiting Enabled", status="success", details=["Auth: 10/min", "Default: 100/min"])

app.add_middleware(RequestIDMiddleware)
logger.info("request_id_tracking_enabled")
rich_logger.print_status("Request ID Tracking Enabled", status="success")

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SecurityHeadersMiddleware)

# ── Exception Handlers ───────────────────────────────────────
@app.exception_handler(AppException)
async def app_exception_handler(request, exc: AppException):
    logger.error("app_error", message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )

@app.exception_handler(Exception)
async def global_error_handler(request, exc: Exception):
    return await global_exception_handler(request, exc)

# ── Static Files ─────────────────────────────────────────────
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ── Routers ──────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(jobs_router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(candidates_router, prefix="/api/public", tags=["Public"])
app.include_router(interviews_router, prefix="/api/interviews", tags=["Interviews"])
app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(enhanced_analytics_router, prefix="/api", tags=["Enhanced Analytics"])
app.include_router(applications_router, prefix="/api/applications", tags=["Applications"])
app.include_router(screening_router, prefix="/api/screening", tags=["Screening"])
app.include_router(user_router, prefix="/api/user", tags=["User"])
app.include_router(notifications_router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(recruiter_router, prefix="/api/recruiter", tags=["Recruiter"])
app.include_router(reclaim_router, prefix="/api/reclaim-requests", tags=["Reclaim Requests"])
app.include_router(email_router, prefix="/api/email", tags=["Email"])
app.include_router(feedback_router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(violations_router, prefix="/api/violations", tags=["Violations"])

# ── Socket.IO ────────────────────────────────────────────────
from app.proctoring.socketio_server import mount_socketio
sio = mount_socketio(app)
rich_logger.print_status("Socket.IO Mounted", status="success")


# ── Background Services (fires AFTER server binds port) ──────
@app.on_event("startup")
async def startup_background_services():
    """Launch all heavy background services AFTER the server is ready."""
    asyncio.create_task(_bootstrap_background_services(app))


# ── Health & Status Endpoints ────────────────────────────────
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return 204 for favicon requests to prevent browser 502 errors."""
    return Response(status_code=204)

@app.get("/")
async def root():
    return {
        "message": "Welcome to SmartHiring API",
        "docs": "/docs" if settings.ENABLE_DOCS else None,
        "health": "/health",
        "version": settings.APP_VERSION,
    }

@app.get("/health")
async def health_check():
    """Lightweight health check — responds immediately, validates cache readiness."""
    from core.cache import get_cache_service

    try:
        get_cache_service()
        cache_ok = True
    except Exception:
        cache_ok = False

    return {
        "status": "healthy",
        "cache": cache_ok,
    }

@app.get("/health/detailed")
async def health_check_detailed():
    """Comprehensive async health check with service status."""
    import time
    from utils.db import get_db
    from core.cache import get_cache_service

    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "services": {}
    }

    # Check MongoDB
    try:
        db = await get_db()
        await db.command('ping')
        health_status["services"]["database"] = {"status": "healthy", "type": "MongoDB Async"}
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["database"] = {"status": "unhealthy", "error": str(e)}

    # Check Cache
    try:
        cache = get_cache_service()
        health_status["services"]["cache"] = {
            "status": "healthy",
            "type": "In-Memory"
        }
    except Exception as e:
        health_status["services"]["cache"] = {"status": "error", "error": str(e)}

    return health_status

@app.get("/api/status")
async def api_status():
    """Detailed API status with async metrics"""
    from utils.db import get_db
    try:
        db = await get_db()
        stats = {
            "users": await db.users.count_documents({}),
            "jobs": await db.jds.count_documents({}),
            "applications": await db.applications.count_documents({}),
            "interviews": await db.interviews.count_documents({}),
        }
        return {"status": "operational", "statistics": stats}
    except Exception as e:
        return {"status": "error", "error": str(e)}
