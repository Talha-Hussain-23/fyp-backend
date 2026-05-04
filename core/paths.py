"""
Configuration settings for SmartHiring backend.
Centralizes all path and directory configurations.
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Directories
LOGS_DIR = BASE_DIR / "logs"
UPLOADS_DIR = BASE_DIR / "uploads"
TEMP_DIR = BASE_DIR / "temp"
TEST_RESULTS_DIR = BASE_DIR / "test_results"

# Ensure directories exist
for dir_path in [LOGS_DIR, UPLOADS_DIR, TEMP_DIR, TEST_RESULTS_DIR]:
    dir_path.mkdir(exist_ok=True)

# File size limits (MB)
MAX_UPLOAD_SIZE_MB = 25
CHUNK_SIZE_MB = 5
MAX_RESUME_SIZE_MB = 10

# Logging configuration
LOG_FILE = LOGS_DIR / "app.log"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Upload configuration
ALLOWED_RESUME_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
ALLOWED_EXTENSIONS = ALLOWED_RESUME_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS

# Database configuration
MONGODB_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "smarthiring")

# Email configuration
EMAIL_LOG_FILE = LOGS_DIR / "email.log"
EMAIL_QUEUE_SIZE = 100

# Test configuration
TEST_RESULTS_FILE = TEST_RESULTS_DIR / "latest_test.txt"

# Temporary file cleanup (days)
TEMP_FILE_RETENTION_DAYS = 7
