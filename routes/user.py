from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from bson import ObjectId
from datetime import datetime, timezone
import os
import uuid
import structlog
from utils import get_db
from core.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter()

@router.get("/profile")
async def get_user_profile(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get current user's profile (Async)"""
    user = await db.users.find_one({"_id": ObjectId(current_user.id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Remove sensitive fields
    user.pop("password", None)
    user.pop("password_reset_token", None)
    user["id"] = str(user.pop("_id"))
    
    return {
        "success": True,
        "user": user
    }

@router.put("/profile")
async def update_user_profile(
    body: dict,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update user profile information (Async)"""
    allowed_fields = ["name", "phone", "company", "bio", "location"]
    update_data = {k: v for k, v in body.items() if k in allowed_fields}
    
    if not update_data:
        return {"success": True, "message": "No changes made"}
    
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": update_data}
    )
    
    logger.info(f"Profile updated for user {current_user.email}")
    
    return {
        "success": True,
        "message": "Profile updated successfully"
    }

@router.put("/settings")
async def update_user_settings(
    body: dict,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update user settings (Async)"""
    allowed_fields = ["email_notifications", "language", "timezone", "theme"]
    update_data = {f"settings.{k}": v for k, v in body.items() if k in allowed_fields}
    
    if not update_data:
        return {"success": True, "message": "No changes made"}
    
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": update_data}
    )
    
    return {
        "success": True,
        "message": "Settings updated successfully"
    }

@router.put("/password")
async def change_password(
    body: dict,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Change user password (Async)"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    current_password = body.get("current_password")
    new_password = body.get("new_password")
    
    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Both current and new password are required")
    
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    # Verify current password
    user = await db.users.find_one({"_id": ObjectId(current_user.id)})
    if not user or not pwd_context.verify(current_password, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # Update password
    hashed_password = pwd_context.hash(new_password)
    await db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {
            "password": hashed_password,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    logger.info(f"Password changed for user {current_user.email}")
    
    return {
        "success": True,
        "message": "Password changed successfully"
    }

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Upload user avatar (Async)"""
    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Allowed: jpg, png, gif, webp")
    
    # Generate unique filename
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    
    # Save file
    upload_dir = "uploads/avatars"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Update user record
    avatar_url = f"/uploads/avatars/{filename}"
    await db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"avatar_url": avatar_url, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    logger.info(f"Avatar uploaded for user {current_user.email}")
    
    return {
        "success": True,
        "avatar_url": avatar_url
    }
