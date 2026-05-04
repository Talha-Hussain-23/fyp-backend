"""
Structured Logging Service
Professional logging with JSON output and proper log levels
"""
import logging
import json
import sys
from datetime import datetime
from typing import Optional, Any
from functools import lru_cache


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra_data"):
            log_obj["data"] = record.extra_data
        
        return json.dumps(log_obj, default=str)


class PrettyFormatter(logging.Formatter):
    """Human-readable colored formatter for development."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        msg = f"{color}[{timestamp}] {record.levelname:8}{self.RESET} | {record.getMessage()}"
        
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"
        
        return msg


class AppLogger:
    """Application logger with structured logging support."""
    
    def __init__(self, name: str = "smarthiring", use_json: bool = False):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        self.logger.handlers.clear()
        
        # Add console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        
        if use_json:
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(PrettyFormatter())
        
        self.logger.addHandler(handler)
    
    def _log(self, level: int, msg: str, **kwargs):
        """Internal log method with extra data support."""
        extra = {"extra_data": kwargs} if kwargs else {}
        self.logger.log(level, msg, extra=extra)
    
    def debug(self, msg: str, **kwargs):
        """Debug level - detailed information for debugging."""
        self._log(logging.DEBUG, msg, **kwargs)
    
    def info(self, msg: str, **kwargs):
        """Info level - general operational messages."""
        self._log(logging.INFO, msg, **kwargs)
    
    def warning(self, msg: str, **kwargs):
        """Warning level - something unexpected but handled."""
        self._log(logging.WARNING, msg, **kwargs)
    
    def error(self, msg: str, **kwargs):
        """Error level - operation failed but app continues."""
        self._log(logging.ERROR, msg, **kwargs)
    
    def critical(self, msg: str, **kwargs):
        """Critical level - serious error, app may crash."""
        self._log(logging.CRITICAL, msg, **kwargs)
    
    def exception(self, msg: str, **kwargs):
        """Error level with exception traceback."""
        self.logger.exception(msg, extra={"extra_data": kwargs} if kwargs else {})


@lru_cache()
def get_logger(name: str = "smarthiring", use_json: bool = False) -> AppLogger:
    """Get or create logger instance (cached)."""
    return AppLogger(name, use_json)


# Default logger instance
logger = get_logger()
