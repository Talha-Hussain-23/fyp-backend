"""
Professional File Handling Configuration
Centralized configuration for all file uploads in SmartHiring
"""

import os
from typing import List, Dict
from enum import Enum

class FileType(Enum):
    """Supported file types"""
    RESUME = "resume"
    PROFILE_PICTURE = "profile_picture"
    PROCTORING_FRAME = "proctoring_frame"
    
class FileConfig:
    """Centralized file handling configuration"""
    
    # ==================== SIZE LIMITS ====================
    # Resume files (PDF, DOCX, Images)
    MAX_RESUME_SIZE_MB = 10  # 10 MB
    MAX_RESUME_SIZE_BYTES = MAX_RESUME_SIZE_MB * 1024 * 1024
    
    # Profile pictures
    MAX_PROFILE_PICTURE_SIZE_MB = 5  # 5 MB
    MAX_PROFILE_PICTURE_SIZE_BYTES = MAX_PROFILE_PICTURE_SIZE_MB * 1024 * 1024
    
    # Proctoring frames (base64 encoded)
    MAX_PROCTORING_FRAME_SIZE_MB = 2  # 2 MB
    MAX_PROCTORING_FRAME_SIZE_BYTES = MAX_PROCTORING_FRAME_SIZE_MB * 1024 * 1024
    
    # ==================== ALLOWED TYPES ====================
    # Resume file types
    ALLOWED_RESUME_TYPES = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "text/plain"
    }
    
    ALLOWED_RESUME_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".jpg",
        ".jpeg",
        ".png",
        ".txt"
    }
    
    # Profile picture types
    ALLOWED_PROFILE_PICTURE_TYPES = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp"
    }
    
    ALLOWED_PROFILE_PICTURE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    }
    
    # ==================== BLOCKED TYPES ====================
    # Security: Block executable and script files
    BLOCKED_EXTENSIONS = {
        ".exe", ".sh", ".bat", ".cmd", ".js", ".vbs", 
        ".scr", ".dll", ".msi", ".app", ".deb", ".rpm",
        ".jar", ".war", ".ear", ".apk", ".ipa",
        ".ps1", ".psm1", ".psd1", ".py", ".rb", ".pl"
    }
    
    BLOCKED_MIME_TYPES = {
        "application/x-msdownload",
        "application/x-executable",
        "application/x-sh",
        "application/x-bat",
        "application/javascript",
        "text/javascript"
    }
    
    # ==================== STORAGE PATHS ====================
    # Base upload directory
    UPLOAD_BASE_DIR = os.getenv("UPLOAD_DIR", "./uploads")
    
    # Subdirectories
    RESUME_UPLOAD_DIR = os.path.join(UPLOAD_BASE_DIR, "resumes")
    PROFILE_PICTURE_DIR = os.path.join(UPLOAD_BASE_DIR, "profile_pictures")
    TEMP_DIR = os.path.join(UPLOAD_BASE_DIR, "temp")
    
    # ==================== PROCESSING LIMITS ====================
    # Text extraction limits (prevent memory exhaustion)
    MAX_TEXT_LENGTH = 50000  # 50K characters
    MAX_PDF_PAGES = 20  # Maximum pages to process in PDF
    
    # OCR limits
    MAX_IMAGE_DIMENSION = 4096  # Max width/height in pixels
    OCR_TIMEOUT_SECONDS = 30  # Timeout for OCR processing
    
    # ==================== CHUNKING CONFIG ====================
    # For large file streaming
    CHUNK_SIZE_BYTES = 1024 * 1024  # 1 MB chunks
    
    @classmethod
    def get_size_limit(cls, file_type: FileType) -> int:
        """Get size limit in bytes for file type"""
        limits = {
            FileType.RESUME: cls.MAX_RESUME_SIZE_BYTES,
            FileType.PROFILE_PICTURE: cls.MAX_PROFILE_PICTURE_SIZE_BYTES,
            FileType.PROCTORING_FRAME: cls.MAX_PROCTORING_FRAME_SIZE_BYTES
        }
        return limits.get(file_type, cls.MAX_RESUME_SIZE_BYTES)
    
    @classmethod
    def get_allowed_types(cls, file_type: FileType) -> set:
        """Get allowed MIME types for file type"""
        types = {
            FileType.RESUME: cls.ALLOWED_RESUME_TYPES,
            FileType.PROFILE_PICTURE: cls.ALLOWED_PROFILE_PICTURE_TYPES,
            FileType.PROCTORING_FRAME: {"image/jpeg", "image/png"}
        }
        return types.get(file_type, cls.ALLOWED_RESUME_TYPES)
    
    @classmethod
    def get_allowed_extensions(cls, file_type: FileType) -> set:
        """Get allowed file extensions for file type"""
        extensions = {
            FileType.RESUME: cls.ALLOWED_RESUME_EXTENSIONS,
            FileType.PROFILE_PICTURE: cls.ALLOWED_PROFILE_PICTURE_EXTENSIONS,
            FileType.PROCTORING_FRAME: {".jpg", ".jpeg", ".png"}
        }
        return extensions.get(file_type, cls.ALLOWED_RESUME_EXTENSIONS)
    
    @classmethod
    def ensure_directories(cls):
        """Create upload directories if they don't exist"""
        directories = [
            cls.UPLOAD_BASE_DIR,
            cls.RESUME_UPLOAD_DIR,
            cls.PROFILE_PICTURE_DIR,
            cls.TEMP_DIR
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)


# Human-readable size formatting
def format_file_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


# Initialize directories on import
FileConfig.ensure_directories()
