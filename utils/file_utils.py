"""
Filename Sanitization Utility
Prevents path traversal and malicious filename attacks
"""
import re
import os
from pathlib import Path


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize filename to prevent path traversal and other attacks
    
    Args:
        filename: Original filename
        max_length: Maximum allowed filename length
        
    Returns:
        Sanitized filename
    """
    if not filename:
        return "file"
    
    # Remove path components (prevents path traversal)
    safe_name = Path(filename).name
    
    # Remove or replace dangerous characters
    # Allow only: alphanumeric, dots, hyphens, underscores
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_name)
    
    # Prevent hidden files (starting with dot)
    if safe_name.startswith('.'):
        safe_name = 'file_' + safe_name
    
    # Prevent double extensions (e.g., file.pdf.exe)
    parts = safe_name.split('.')
    if len(parts) > 2:
        # Keep only last extension
        name = '_'.join(parts[:-1])
        ext = parts[-1]
        safe_name = f"{name}.{ext}"
    
    # Limit length
    if len(safe_name) > max_length:
        name, ext = os.path.splitext(safe_name)
        max_name_length = max_length - len(ext)
        safe_name = name[:max_name_length] + ext
    
    # Ensure we have a filename
    if not safe_name or safe_name == '.':
        safe_name = 'file'
    
    return safe_name


def get_safe_upload_path(base_dir: str, filename: str, user_id: str = None) -> str:
    """
    Generate safe upload path with optional user isolation
    
    Args:
        base_dir: Base upload directory
        filename: Original filename
        user_id: Optional user ID for isolation
        
    Returns:
        Safe absolute path for file upload
    """
    safe_filename = sanitize_filename(filename)
    
    if user_id:
        # Create user-specific subdirectory
        user_dir = os.path.join(base_dir, sanitize_filename(user_id))
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, safe_filename)
    
    return os.path.join(base_dir, safe_filename)


def validate_file_extension(filename: str, allowed_extensions: set) -> bool:
    """
    Validate file extension against allowed list
    
    Args:
        filename: Filename to validate
        allowed_extensions: Set of allowed extensions (without dot)
        
    Returns:
        True if extension is allowed
    """
    ext = Path(filename).suffix.lower().lstrip('.')
    return ext in allowed_extensions
