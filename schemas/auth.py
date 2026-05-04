"""
Authentication Schemas
Models for user registration, login, and profile management
"""
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user fields."""
    email: EmailStr
    name: str


class UserCreate(UserBase):
    """User registration model."""
    password: str = Field(min_length=6)
    is_recruiter: bool = False
    invite_code: Optional[str] = None


class UserLogin(BaseModel):
    """User login model."""
    username: EmailStr  # OAuth2PasswordRequestForm uses 'username' field 
    password: str


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int


class SignupResponse(BaseModel):
    """User registration response."""
    message: str
    email: EmailStr
    user_id: str
    verification_sent: bool = True
    requires_verification: bool = True


class RefreshTokenRequest(BaseModel):
    """Request model for refreshing access token."""
    refresh_token: str


class TokenData(BaseModel):
    """Data stored in JWT token."""
    sub: Optional[str] = None
    exp: Optional[int] = None


class ProfileUpdate(BaseModel):
    """User profile update model."""
    name: Optional[str] = None
    organization: Optional[str] = None
    role: Optional[str] = None
    bio: Optional[str] = None


class PasswordChange(BaseModel):
    """Password change model."""
    current_password: str
    new_password: str = Field(min_length=6)


class PasswordResetRequest(BaseModel):
    """Password reset request model."""
    email: EmailStr


class EmailRequest(BaseModel):
    """Generic request with email field."""
    email: EmailStr


class PasswordResetBody(BaseModel):
    """Password reset completion model."""
    new_password: str = Field(min_length=6)


class UserResponse(UserBase):
    """User profile response."""
    id: str
    is_recruiter: bool
    is_verified: bool = False
    organization: Optional[str] = None
    role: Optional[str] = None
    
    class Config:
        from_attributes = True
