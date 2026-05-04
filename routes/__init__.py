"""
Router Package
Exports all API routers
"""
from .auth import router as auth_router
from .jobs import router as jobs_router
from .candidates import router as candidates_router
from .interviews import router as interviews_router
from .analytics import router as analytics_router
from .applications import router as applications_router
from .screening import router as screening_router
from .user import router as user_router
from .notifications import router as notifications_router
from .recruiter import router as recruiter_router
from .reclaim import router as reclaim_router
from .email import router as email_router
from .feedback import router as feedback_router

# Export routers for app.py
__all__ = [
    "auth_router", 
    "jobs_router", 
    "candidates_router",
    "interviews_router",
    "analytics_router",
    "applications_router",
    "screening_router",
    "user_router",
    "notifications_router",
    "recruiter_router",
    "reclaim_router",
    "email_router",
    "feedback_router"
]



