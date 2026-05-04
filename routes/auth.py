"""
Authentication Routes
Refactored auth endpoints using modular router and schemas
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from schemas import (
    UserCreate, 
    UserLogin, 
    Token, 
    UserResponse,
    PasswordResetRequest,
    PasswordResetBody,
    ProfileUpdate,
    EmailRequest,
    RefreshTokenRequest,
    SignupResponse
)
from utils import (
    get_db, 
    AppException
)
import structlog
from core.auth import (
    signup, 
    login, 
    get_current_user, 
    request_password_reset, 
    reset_password,
    verify_email,
    resend_verification_email,
    invalidate_tokens
)

logger = structlog.get_logger(__name__)
from bson import ObjectId
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

router = APIRouter()

from core.rate_limiter import limiter

@router.post("/signup", response_model=SignupResponse)
@limiter.limit("10/minute")
async def signup_route(request: Request, user: UserCreate, db = Depends(get_db)):
    """Create new user account (recruiter or candidate)"""
    try:
        result = await signup(user, db, request=request)  # Pass request for IP tracking
        logger.info("new_user_signed_up", email=user.email)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("signup_failed", email=user.email, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login_route(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db = Depends(get_db)
):
    """User login with JWT token"""
    try:
        result = await login(form_data, db)
        logger.info("user_logged_in", username=form_data.username)
        return result
    except Exception as e:
        logger.error("login_failed", username=form_data.username, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/refresh", response_model=Token)
async def refresh_token_route(
    request: RefreshTokenRequest,
    db = Depends(get_db)
):
    """Refresh expired access token using refresh token"""
    try:
        from core.auth import refresh_access_token
        result = await refresh_access_token(request.refresh_token, db)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("token_refresh_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user = Depends(get_current_user)):
    """Get current authenticated user"""
    """Get current authenticated user"""
    return current_user

@router.post("/logout")
async def logout(current_user = Depends(get_current_user), db = Depends(get_db)):
    """
    Logout user from all devices.
    Invalidates all existing tokens by incrementing the token version.
    """
    success = await invalidate_tokens(current_user.id, db)
    if not success:
        raise HTTPException(status_code=500, detail="Logout failed")
    
    return {"message": "Logged out successfully"}

@router.post("/request-password-reset")
@limiter.limit("3/hour")  # ✅ SECURITY FIX: Rate limit password reset
async def request_password_reset_route(request: Request, email_req: EmailRequest, db = Depends(get_db)):
    """Request password reset email"""
    return await request_password_reset(email_req.email, db)

@router.post("/reset-password/{token}")
async def reset_password_route(token: str, body: PasswordResetBody, db = Depends(get_db)):
    """Reset password using token"""
    return await reset_password(token, body.new_password, db)

@router.get("/verify/{token}")
async def verify_email_route(token: str, db = Depends(get_db)):
    """Verify email address"""
    return await verify_email(token, db)

@router.post("/send-verification")
@limiter.limit("5/hour")  # ✅ SECURITY FIX: Rate limit email verification
async def send_verification_route(request: Request, email_req: EmailRequest, db = Depends(get_db)):
    """Resend email verification"""
    return await resend_verification_email(email_req.email, db)

