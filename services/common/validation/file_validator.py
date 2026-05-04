"""
Professional File Validation Service
Validates file uploads for size, type, and security
"""

from fastapi import UploadFile, HTTPException
from typing import Optional
import os

# Try to import python-magic, but make it optional
try:
    import magic  # python-magic for MIME type detection
    MAGIC_AVAILABLE = True
except (ImportError, OSError) as e:
    # libmagic not installed or python-magic not available
    MAGIC_AVAILABLE = False
    magic = None

from core.file_config import FileConfig, FileType, format_file_size
from core.logging_service import logger
from utils.file_utils import sanitize_filename  # ✅ SECURITY FIX: Path traversal prevention


class FileValidator:
    """Professional file validation with security checks"""
    
    @staticmethod
    async def validate_file(
        file: UploadFile,
        file_type: FileType,
        check_content: bool = True
    ) -> dict:
        """
        Comprehensive file validation
        
        Args:
            file: Uploaded file
            file_type: Type of file (RESUME, PROFILE_PICTURE, etc.)
            check_content: Whether to validate actual file content (slower but more secure)
        
        Returns:
            dict with validation results
        
        Raises:
            HTTPException if validation fails
        """
        filename = file.filename or "unknown"
        
        # 1. Check filename
        if not filename or filename == "unknown":
            raise HTTPException(
                status_code=400,
                detail="Filename is required"
            )
        
        # ✅ SECURITY FIX: Sanitize filename to prevent path traversal
        filename = sanitize_filename(filename)
        
        # 2. Extract extension
        file_extension = os.path.splitext(filename)[1].lower()
        
        # 3. Security check: Block dangerous extensions
        if file_extension in FileConfig.BLOCKED_EXTENSIONS:
            logger.warning(f"🚨 SECURITY: Blocked dangerous file type: {filename}")
            raise HTTPException(
                status_code=400,
                detail=f"Security Error: {file_extension} files are not allowed for security reasons"
            )
        
        # 4. Check allowed extensions
        allowed_extensions = FileConfig.get_allowed_extensions(file_type)
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # 5. Check MIME type from header
        declared_mime = file.content_type
        if declared_mime in FileConfig.BLOCKED_MIME_TYPES:
            logger.warning(f"🚨 SECURITY: Blocked dangerous MIME type: {declared_mime}")
            raise HTTPException(
                status_code=400,
                detail="Security Error: This file type is not allowed"
            )
        
        allowed_types = FileConfig.get_allowed_types(file_type)
        if declared_mime not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid MIME type. Allowed: {', '.join(allowed_types)}"
            )
        
        # 6. Read file content for size and content validation
        content = await file.read()
        file_size = len(content)
        await file.seek(0)  # Reset file pointer
        
        # 7. Check file size
        max_size = FileConfig.get_size_limit(file_type)
        if file_size > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {format_file_size(max_size)}, "
                       f"your file: {format_file_size(file_size)}"
            )
        
        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="File is empty"
            )
        
        # 8. Content-based validation (optional, more secure but slower)
        actual_mime = declared_mime
        if check_content and MAGIC_AVAILABLE:
            try:
                # Use python-magic to detect actual MIME type from content
                actual_mime = magic.from_buffer(content, mime=True)
                
                # Verify actual MIME matches declared MIME (prevent spoofing)
                if actual_mime not in allowed_types:
                    logger.warning(
                        f"⚠️  MIME mismatch: declared={declared_mime}, "
                        f"actual={actual_mime} for {filename}"
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"File content doesn't match declared type. "
                               f"Expected: {declared_mime}, Detected: {actual_mime}"
                    )
            except Exception as e:
                logger.warning(f"Content validation failed: {e}")
                # Continue with declared MIME if magic fails
        elif check_content and not MAGIC_AVAILABLE:
            logger.info(
                "⚠️  Content validation skipped: python-magic/libmagic not available. "
                "Install python-magic-bin (Windows) or libmagic (Linux/Mac) for enhanced security."
            )
        
        logger.info(
            f"✅ File validated: {filename} "
            f"({format_file_size(file_size)}, {actual_mime})"
        )
        
        return {
            "valid": True,
            "filename": filename,
            "size": file_size,
            "size_formatted": format_file_size(file_size),
            "mime_type": actual_mime,
            "extension": file_extension
        }
    
    @staticmethod
    async def validate_resume(file: UploadFile) -> dict:
        """Validate resume file"""
        return await FileValidator.validate_file(
            file,
            FileType.RESUME,
            check_content=True  # Enable content validation for resumes
        )
    
    @staticmethod
    async def validate_profile_picture(file: UploadFile) -> dict:
        """Validate profile picture"""
        return await FileValidator.validate_file(
            file,
            FileType.PROFILE_PICTURE,
            check_content=True
        )
    
    @staticmethod
    def validate_base64_frame(frame_data: str, max_size_mb: float = 2.0) -> dict:
        """
        Validate base64 encoded proctoring frame
        
        Args:
            frame_data: Base64 encoded image string
            max_size_mb: Maximum size in MB
        
        Returns:
            dict with validation results
        """
        import base64
        
        if not frame_data:
            raise HTTPException(
                status_code=400,
                detail="Frame data is empty"
            )
        
        # Remove data URL prefix if present
        if frame_data.startswith('data:image'):
            frame_data = frame_data.split(',')[1]
        
        # Calculate size
        try:
            decoded = base64.b64decode(frame_data)
            size_bytes = len(decoded)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 data: {str(e)}"
            )
        
        max_size_bytes = int(max_size_mb * 1024 * 1024)
        if size_bytes > max_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Frame too large. Maximum: {format_file_size(max_size_bytes)}, "
                       f"received: {format_file_size(size_bytes)}"
            )
        
        return {
            "valid": True,
            "size": size_bytes,
            "size_formatted": format_file_size(size_bytes)
        }
