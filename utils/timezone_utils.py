"""
Timezone utility functions for handling job deadlines
Converts deadlines to UTC for consistent storage and comparison
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import os
import re
from core.logging_service import logger


def get_default_timezone_offset() -> int:
    """
    Get default timezone offset in hours.
    Can be set via environment variable DEFAULT_TIMEZONE_OFFSET (e.g., "5" for UTC+5)
    Defaults to 5 (Pakistan Time) if not set.
    """
    offset_str = os.getenv("DEFAULT_TIMEZONE_OFFSET", "5")
    try:
        return int(offset_str)
    except ValueError:
        return 5  # Default to Pakistan Time (UTC+5)


def normalize_deadline_to_utc(deadline_str: Optional[str]) -> Optional[str]:
    """
    Normalize a deadline string to UTC format.
    
    Handles various input formats:
    - "2025-11-20T17:00:00Z" -> "2025-11-20T12:00:00Z" (if UTC, keeps as is)
    - "2025-11-20T17:00:00+05:00" -> "2025-11-20T12:00:00Z" (converts from PKT to UTC)
    - "2025-11-20T17:00:00" -> "2025-11-20T12:00:00Z" (assumes local time, converts to UTC)
    
    Args:
        deadline_str: Deadline string in various formats
        
    Returns:
        Deadline string in UTC format with 'Z' suffix, or None if input is None/invalid
    """
    if not deadline_str or not deadline_str.strip():
        return None
    
    deadline_str = deadline_str.strip()
    
    try:
        # Case 1: Already has timezone info (Z or +XX:XX)
        if 'Z' in deadline_str or '+' in deadline_str or deadline_str.count('-') >= 3:
            # Parse with timezone
            if 'Z' in deadline_str:
                # UTC format: "2025-11-20T12:00:00Z"
                dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
            else:
                # Has timezone offset: "2025-11-20T17:00:00+05:00"
                dt = datetime.fromisoformat(deadline_str)
            
            # Convert to UTC
            if dt.tzinfo:
                dt_utc = dt.astimezone(timezone.utc)
            else:
                dt_utc = dt
            
            # Return in UTC format with 'Z'
            return dt_utc.replace(tzinfo=None).isoformat() + 'Z'
        
        # Case 2: No timezone info - assume it's in default timezone (e.g., Pakistan Time UTC+5)
        else:
            # Parse as naive datetime
            dt = datetime.fromisoformat(deadline_str)
            
            # Assume it's in the default timezone (e.g., UTC+5 for Pakistan)
            default_offset = get_default_timezone_offset()
            local_tz = timezone(timedelta(hours=default_offset))
            
            # Make it timezone-aware
            dt_local = dt.replace(tzinfo=local_tz)
            
            # Convert to UTC
            dt_utc = dt_local.astimezone(timezone.utc)
            
            # Return in UTC format with 'Z'
            return dt_utc.replace(tzinfo=None).isoformat() + 'Z'
    
    except (ValueError, AttributeError) as e:
        # Try alternative parsing with dateutil if available
        try:
            from dateutil import parser
            dt = parser.parse(deadline_str)
            
            # If no timezone, assume default
            if dt.tzinfo is None:
                default_offset = get_default_timezone_offset()
                local_tz = timezone(timedelta(hours=default_offset))
                dt = dt.replace(tzinfo=local_tz)
            
            # Convert to UTC
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.replace(tzinfo=None).isoformat() + 'Z'
        
        except Exception:
            # If all parsing fails, log warning and return None
            logger.warning(f"Warning: Could not parse deadline '{deadline_str}'. Error: {e}")
            return None


def parse_deadline_from_utc(deadline_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a deadline string to datetime object (naive UTC).
    Used for comparisons in background tasks.
    
    IMPORTANT: If deadline has no timezone info, assumes it's in LOCAL timezone
    (e.g., Pakistan Time UTC+5) and converts to UTC. This handles old deadlines
    that were stored without timezone information.
    
    Args:
        deadline_str: Deadline string (can be UTC with 'Z', with timezone, or naive)
        
    Returns:
        Naive datetime object in UTC, or None if invalid
    """
    if not deadline_str:
        return None
    
    try:
        # Case 1: Has timezone info (Z or +XX:XX) - parse and convert to UTC
        if 'Z' in deadline_str:
            # UTC format: "2025-11-21T01:18:00Z"
            dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
        elif '+' in deadline_str or (deadline_str.count('-') >= 3 and 'T' in deadline_str):
            # Has timezone offset: "2025-11-21T01:18:00+05:00"
            dt = datetime.fromisoformat(deadline_str)
        else:
            # Case 2: No timezone info - assume it's in LOCAL timezone (e.g., PKT UTC+5)
            # This handles old deadlines stored before timezone fix
            dt = datetime.fromisoformat(deadline_str)
            
            # Assume it's in the default timezone (e.g., UTC+5 for Pakistan)
            default_offset = get_default_timezone_offset()
            local_tz = timezone(timedelta(hours=default_offset))
            
            # Make it timezone-aware
            dt = dt.replace(tzinfo=local_tz)
        
        # Convert to naive UTC
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        
        return dt
    
    except (ValueError, AttributeError):
        try:
            from dateutil import parser
            dt = parser.parse(deadline_str)
            
            # If no timezone, assume default local timezone
            if dt.tzinfo is None:
                default_offset = get_default_timezone_offset()
                local_tz = timezone(timedelta(hours=default_offset))
                dt = dt.replace(tzinfo=local_tz)
            
            # Convert to UTC
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            return None


def utc_to_local(utc_time: datetime, offset_hours: int = 5) -> datetime:
    """
    Convert UTC datetime to local time (default UTC+5).
    
    Args:
        utc_time: Datetime object in UTC (naive or timezone-aware)
        offset_hours: Timezone offset in hours (default 5 for Pakistan)
        
    Returns:
        Datetime object in local time (naive)
    """
    if utc_time.tzinfo:
        utc_time = utc_time.replace(tzinfo=None)
    
    return utc_time + timedelta(hours=offset_hours)


def format_local_time(utc_time: datetime, offset_hours: int = 5) -> str:
    """
    Convert UTC datetime to local time string with timezone indicator.
    
    Args:
        utc_time: Datetime object in UTC
        offset_hours: Timezone offset in hours (default 5 for Pakistan)
        
    Returns:
        Formatted string like "2025-11-21 08:43:02 UTC+5"
    """
    local_time = utc_to_local(utc_time, offset_hours)
    return f"{local_time.strftime('%Y-%m-%d %H:%M:%S')} UTC+{offset_hours}"


def utc_str_to_local_str(utc_str: Optional[str], offset_hours: int = 5) -> Optional[str]:
    """
    Convert UTC datetime string to local time string.
    
    Args:
        utc_str: ISO format datetime string in UTC (e.g., "2025-11-21T01:18:00Z")
        offset_hours: Timezone offset in hours (default 5 for Pakistan)
        
    Returns:
        Local time string like "2025-11-21 06:18:00 UTC+5" or None if invalid
    """
    if not utc_str:
        return None
    
    try:
        # Parse the UTC time
        dt = parse_deadline_from_utc(utc_str)
        if not dt:
            return None
        
        return format_local_time(dt, offset_hours)
    except Exception:
        return None
