import secrets
import hashlib
import os
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from bson import ObjectId
import structlog

from core.config import settings
from services.notification.notification_service import create_notification

logger = structlog.get_logger(__name__)

# Load environment variables
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Security setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Pydantic model for user creation
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    is_recruiter: bool = False
    invite_code: str = None

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def validate_password_strength(password: str) -> dict:
    """
    Validate password strength and return detailed feedback
    Returns: {"valid": bool, "message": str, "errors": list}
    """
    errors = []
    
    # Minimum length
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    
    # Check for uppercase
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    
    # Check for lowercase
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    
    # Check for digit
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one number")
    
    # Check for special character
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        errors.append("Password must contain at least one special character (!@#$%^&*...)")
    
    if errors:
        return {
            "valid": False,
            "message": "; ".join(errors),
            "errors": errors
        }
    
    return {
        "valid": True,
        "message": "Password meets all requirements",
        "errors": []
    }

def create_access_token(data: dict, token_version: int = 0):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "v": token_version, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, token_version: int = 0):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "v": token_version, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def signup(user: UserCreate, db, request: Request = None):
    """
    Create a new user in MongoDB with email verification (Async).
    Includes brute force protection for recruiter signups.
    """
    # STEP 1: Check IP-based brute force protection (if request provided)
    client_ip = None
    if request:
        from core.rate_limiter import get_real_ip
        from middleware.signup_protection import is_ip_blocked, get_retry_after, record_failed_attempt, clear_attempts
        
        client_ip = get_real_ip(request)
        
        if is_ip_blocked(client_ip):
            retry_after = get_retry_after(client_ip)
            logger.warning("signup_blocked_rate_limit", ip=client_ip, retry_after=retry_after)
            raise HTTPException(
                status_code=429,
                detail=f"Too many signup attempts. Please try again in {retry_after} minute(s).",
                headers={"Retry-After": str(retry_after * 60)}
            )
    
    # Check if user already exists
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Validate password strength
    password_validation = validate_password_strength(user.password)
    if not password_validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=password_validation["message"]
        )

    # STEP 2: Validate Recruiter Invite Code
    if user.is_recruiter:
        # Get code from env (support both variable names)
        valid_code = os.getenv("RECRUITER_INVITE_CODE")
        if not valid_code:
            # Fatal error if not configured
            raise HTTPException(
                status_code=500,
                detail="System configuration error: Invite code not set."
            )
            
        if not user.invite_code or user.invite_code != valid_code:
            # Record failed attempt
            if request and client_ip:
                is_blocked = record_failed_attempt(client_ip)
                if is_blocked:
                    retry_after = get_retry_after(client_ip)
                    raise HTTPException(
                        status_code=429,
                        detail=f"Too many failed attempts. Please try again in {retry_after} minute(s).",
                        headers={"Retry-After": str(retry_after * 60)}
                    )
            
            # Log security event
            logger.warning(
                "invalid_invite_code",
                email=user.email,
                ip=client_ip or "unknown"
            )
            
            raise HTTPException(
                status_code=403,
                detail="Invalid Recruiter Invite Code. Please contact support."
            )
    
    # STEP 3: Clear attempts on successful validation
    if request and client_ip:
        clear_attempts(client_ip)
    
    hashed_password = get_password_hash(user.password)
    from core.models import create_user_document
    
    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    hashed_verification_token = hashlib.sha256(verification_token.encode()).hexdigest()
    
    user_doc = create_user_document(user.name, user.email, hashed_password, user.is_recruiter)
    user_doc["verification_token"] = hashed_verification_token
    
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    
    # Send verification email
    try:
        from services.email.email_service import send_email_verification_email
        await send_email_verification_email(
            to_email=user.email,
            user_name=user.name,
            verification_token=verification_token,
            db=db
        )
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        # Don't fail signup if email fails, user can request resend
    
    # Log successful signup
    role = "recruiter" if user.is_recruiter else "candidate"
    logger.info(
        "user_signed_up",
        role=role,
        email=user.email,
        ip=client_ip or "unknown"
    )

    # Send Welcome Notification (Exceptional)
    try:
        await create_notification(
            db=db,
            user_id=user_id,
            title="Welcome to SmartHiring! 🎉",
            message=f"Hi {user.name}, your account is created. Please verify your email to continue.",
            notification_type="success",
            link="/settings/notifications"
        )
    except Exception as e:
        logger.error(f"Failed to create welcome notification: {e}")
    
    # ✅ SECURITY FIX: Don't return tokens until email is verified
    # User must verify email before they can login
    return {
        "message": "Account created successfully. Please check your email to verify your account before logging in.",
        "email": user.email,
        "user_id": user_id,
        "verification_sent": True,
        "requires_verification": True
    }

async def login(form_data: OAuth2PasswordRequestForm, db):
    """Authenticate user from MongoDB (Async)"""
    # Auto-strip whitespace
    email = form_data.username.strip()
    
    user = await db.users.find_one({"email": email})
    
    # Check if user exists
    if not user:
        # ✅ SECURITY FIX: Generic error message to prevent email enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check password
    if not verify_password(form_data.password, user["hashed_password"]):
        # ✅ SECURITY FIX: Generic error message
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # SECURITY CHECK: Verify account is active
    if not user.get("is_active", True):
        logger.warning("login_denied_deactivated_account", email=email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deactivated. Please contact support.",
        )
    
    # Check if email is verified
    if not user.get("is_verified", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox and verify your account before logging in.",
        )
    
    expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    # Use current token version from user doc, default to 0 if missing
    token_version = user.get("token_version", 0)
    access_token = create_access_token(data={"sub": str(user["_id"])}, token_version=token_version)
    refresh_token = create_refresh_token(data={"sub": str(user["_id"])}, token_version=token_version)
    
    # Log successful login
    role = user.get("role", "candidate")
    logger.info("user_login_success", email=email, role=role)
    
    return {
        "access_token": access_token, 
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in
    }

async def refresh_access_token(refresh_token: str, db):
    """Refresh access token using a valid refresh token (Async)"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode token
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        token_version: int = payload.get("v", 0)
        
        if user_id is None:
            raise credentials_exception
            
        # Ensure it's strictly a Refresh Token
        if token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
    except JWTError:
        raise credentials_exception
    
    # Check User in DB
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise credentials_exception
        
    # Check Token Version (Revocation Check)
    current_version = user.get("token_version", 0)
    if token_version != current_version:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired (Token Revoked). Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
         
    # Generate new Access Token
    expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    new_access_token = create_access_token(
        data={"sub": user_id}, 
        token_version=current_version
    )
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": expires_in
    }


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get current authenticated user from MongoDB"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Import here to avoid circular dependency
    from utils.db import get_db
    db = await get_db()
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise credentials_exception
        
        # Verify token version
        current_version = user.get("token_version", 0)
        token_version = payload.get("v", 0)
        
        if token_version != current_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Create a simple object that mimics the user
        class UserObj:
            """User object with authentication and authorization fields"""
            def __init__(self, user_doc):
                self.id = str(user_doc["_id"])
                self.name = user_doc.get("name", user_doc.get("email", "User"))
                self.email = user_doc["email"]
                self.is_recruiter = bool(user_doc.get("is_recruiter", False))
                self.role = user_doc.get("role", "candidate")  # Explicit role field
                self.is_active = user_doc.get("is_active", True)  # Account activation status
                self.token_version = user_doc.get("token_version", 0)
        
        return UserObj(user)
    except Exception:
        raise credentials_exception


async def invalidate_tokens(user_id: str, db):
    """
    Invalidate all existing tokens for a user by incrementing their token version (Async).
    Forces logout on all devices.
    """
    try:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"token_version": 1}}
        )
        return True
    except Exception as e:
        logger.error("token_invalidation_failed", user_id=str(user_id), error=str(e))
        return False


async def decode_token_async(token: str):
    """
    Decode JWT token and return user object (Asynchronous)
    Used by FastAPI/Socket.IO where non-blocking I/O is required
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    
    from utils.db import get_db
    try:
        db = await get_db()
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return None
        
        class UserObj:
            def __init__(self, user_doc):
                self.id = str(user_doc["_id"])
                self.name = user_doc.get("name", user_doc.get("email", "User"))
                self.email = user_doc["email"]
                self.is_recruiter = bool(user_doc.get("is_recruiter", False))
        
        return UserObj(user)
    except Exception as e:
        logger.error(f"Error decoding token (async): {e}")
        return None


def decode_token(token: str):
    """
    Decode JWT token and return user object (Synchronous)
    Used by Flask-SocketIO where blocking I/O is necessary
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    
    from utils.db import get_db_sync
    try:
        db = get_db_sync()
        user = db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return None
        
        class UserObj:
            def __init__(self, user_doc):
                self.id = str(user_doc["_id"])
                self.name = user_doc.get("name", user_doc.get("email", "User"))
                self.email = user_doc["email"]
                self.is_recruiter = bool(user_doc.get("is_recruiter", False))
        
        return UserObj(user)
    except Exception as e:
        logger.error(f"Error decoding token (sync): {e}")
        return None


def generate_reset_token():
    """Generate a secure reset token and its hash"""
    token = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    return token, hashed_token


async def request_password_reset(email: str, db):
    """Request password reset - generate token and send email (Async)"""
    user = await db.users.find_one({"email": email})
    if not user:
        # Don't reveal if email exists for security
        return {"success": True, "message": "If the email exists, a password reset link has been sent."}
    
    # Generate reset token
    reset_token, hashed_token = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    
    # Store hashed token and expiration
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "password_reset_token": hashed_token,
            "password_reset_expires": expires_at.isoformat()
        }}
    )
    
    # Send reset email
    try:
        from services.email.email_service import send_password_reset_email
        await send_password_reset_email(
            to_email=user["email"],
            user_name=user.get("name", user["email"]),
            reset_token=reset_token,
            db=db
        )
    except Exception as e:
        logger.error(f"⚠️  Failed to send password reset email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send password reset email")
    
    return {"success": True, "message": "Password reset email sent successfully"}


async def reset_password(token: str, new_password: str, db):
    """Reset password using token (Async)"""
    # Validate password strength first
    password_validation = validate_password_strength(new_password)
    if not password_validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=password_validation["message"]
        )
    
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    
    # Find user with valid token
    user = await db.users.find_one({
        "password_reset_token": hashed_token,
        "password_reset_expires": {"$gt": datetime.now(timezone.utc).isoformat()}
    })
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Update password and clear reset token
    hashed_password = get_password_hash(new_password)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "hashed_password": hashed_password,
            "password_reset_token": None,
            "password_reset_expires": None
        }, "$inc": {"token_version": 1}}
    )
    
    # Send confirmation email
    try:
        from services.email.email_service import send_password_changed_email
        await send_password_changed_email(
            to_email=user["email"],
            user_name=user.get("name", user["email"]),
            db=db
        )
    except Exception as e:
        logger.error(f"⚠️  Failed to send password changed email: {e}")
    
    return {"success": True, "message": "Password reset successfully"}


async def verify_email(token: str, db):
    """Verify user email using verification token (Async)"""
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    
    # Find user with verification token
    user = await db.users.find_one({"verification_token": hashed_token})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token"
        )
    
    if user.get("is_verified", False):
        return {"success": True, "message": "Email already verified"}
    
    # Mark as verified
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "is_verified": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "verification_token": None
        }}
    )
    
    return {"success": True, "message": "Email verified successfully"}


async def resend_verification_email(email: str, db):
    """Resend verification email (Async)"""
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.get("is_verified", False):
        raise HTTPException(status_code=400, detail="Email already verified")
    
    # Generate new verification token
    verification_token = secrets.token_urlsafe(32)
    hashed_verification_token = hashlib.sha256(verification_token.encode()).hexdigest()
    
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"verification_token": hashed_verification_token}}
    )
    
    # Send verification email
    try:
        from services.email.email_service import send_email_verification_email
        await send_email_verification_email(
            to_email=user["email"],
            user_name=user.get("name", user["email"]),
            verification_token=verification_token,
            db=db
        )
    except Exception as e:
        logger.error(f"⚠️  Failed to send verification email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification email")
    
    return {"success": True, "message": "Verification email sent successfully"}
