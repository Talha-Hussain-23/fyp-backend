"""
SmartHiring API - Centralized Configuration
All settings are loaded from environment variables via .env file.
The backend will fail gracefully if required variables are missing.
"""
from typing import List, Union, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, Field, field_validator
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Explicitly load .env file to ensure environment variables are populated
env_path = BASE_DIR / ".env"
load_dotenv(env_path)


class Settings(BaseSettings):
    # ─── App Config ───────────────────────────────────────────────
    APP_NAME: str = "SmartHiring API"
    APP_VERSION: str = "2.0.0"
    API_V1_STR: str = "/api"
    ENVIRONMENT: str = Field(default="production")
    DEBUG: bool = Field(default=False)

    # ─── Server Config ────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ─── CORS ─────────────────────────────────────────────────────
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "https://smarthiring.vercel.app",
        "https://fyp-frontend-pi-tan.vercel.app"
    ]

    # ─── Database (Required) ──────────────────────────────────────
    MONGODB_URI: str = Field(validation_alias="MONGO_URI")
    MONGODB_DB: str = Field(default="HiringProcess")
    DATABASE_NAME: str = Field(default="HiringProcess", validation_alias="MONGODB_DB")

    # ─── Connection Pool Tuning ───────────────────────────────────
    MIN_POOL_SIZE: int = 1
    MAX_POOL_SIZE: int = 50
    MAX_IDLE_TIME_MS: int = 45000

    # ─── Caching Layer ────────────────────────────────────────────
    CACHE_SIZE_LIMIT: int = 2000
    CACHE_DEFAULT_TTL: int = 3600

    # ─── Security (Required) ─────────────────────────────────────
    SECRET_KEY: str = Field(default="temporary-secret-key-for-dev")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    JWT_ALGORITHM: str = "HS256"

    # ─── AI Services ──────────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ─── Email ────────────────────────────────────────────────────
    GMAIL_CLIENT_ID: Optional[str] = None
    GMAIL_CLIENT_SECRET: Optional[str] = None
    GMAIL_USER: Optional[str] = None
    GMAIL_CREDENTIALS_PATH: str = "credentials.json"
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None
    GOOGLE_TOKEN_JSON: Optional[str] = None

    # ─── Frontend URLs ────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:3000"
    BASE_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    # ─── Real-Time / Socket.IO ────────────────────────────────────
    SOCKETIO_CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    PROCTORING_SERVER_PORT: int = 5000
    PROCTORING_SERVER_HOST: str = "0.0.0.0"

    # ─── Rate Limiting ────────────────────────────────────────────
    RATE_LIMIT_AUTH: int = 10
    RATE_LIMIT_PUBLIC: int = 60
    RATE_LIMIT_AUTHENTICATED: int = 100

    # ─── Paths (Computed) ─────────────────────────────────────────
    BASE_DIR: Path = BASE_DIR
    LOGS_DIR: Path = BASE_DIR / "logs"
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    TEMP_DIR: Path = BASE_DIR / "temp"

    # ─── File Limits ──────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 25
    ALLOWED_RESUME_EXTENSIONS: str = "pdf,doc,docx"
    UPLOAD_DIR: str = "uploads"

    # ─── Proctoring Settings ──────────────────────────────────────
    YOLO_MODEL_PATH: str = "yolov8n.pt"
    YOLO_CONFIDENCE_THRESHOLD: float = 0.5
    MAX_PERSON_VIOLATIONS: int = 3
    MAX_PHONE_VIOLATIONS: int = 2
    MAX_TAB_SWITCHES: int = 5

    # ─── Interview Settings ───────────────────────────────────────
    DEFAULT_INTERVIEW_DURATION: int = 60
    AUTO_TERMINATE_ON_TIMEOUT: bool = True
    ALLOW_RECLAIM_REQUESTS: bool = True

    # ─── Logging ──────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    AUDIT_LOGGING_ENABLED: bool = True

    # ─── Development Tools (off by default in production) ─────────
    ENABLE_DOCS: bool = Field(default=False)
    DETAILED_ERRORS: bool = Field(default=False)

    # ─── Brute Force Protection ───────────────────────────────────
    MAX_SIGNUP_ATTEMPTS: int = 5
    SIGNUP_BLOCK_TIME: int = 60

    # ─── Recruiter Invite Code ────────────────────────────────────
    RECRUITER_INVITE_CODE: Optional[str] = None

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    def get_log_dir(self) -> Path:
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        return self.LOGS_DIR


def _validate_required_settings(s: "Settings") -> None:
    """Fail fast if critical environment variables are missing or insecure."""
    import structlog
    _log = structlog.get_logger()

    errors = []

    if not s.MONGODB_URI or "mongodb" not in s.MONGODB_URI.lower():
        errors.append("MONGO_URI is missing or invalid")

    if s.SECRET_KEY == "temporary-secret-key-for-dev" and s.ENVIRONMENT == "production":
        errors.append("SECRET_KEY must be set to a strong random value in production")

    if errors:
        for err in errors:
            _log.critical("config_validation_failed", error=err)
        sys.exit(1)

    # Non-fatal warnings
    if not s.GROQ_API_KEY and not s.GEMINI_API_KEY:
        _log.warning("no_ai_keys_configured", detail="AI question generation will be unavailable")

    if s.DEBUG and s.ENVIRONMENT == "production":
        _log.warning("debug_enabled_in_production", detail="DEBUG=True in production environment")


settings = Settings()
_validate_required_settings(settings)
