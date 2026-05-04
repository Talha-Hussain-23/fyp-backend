# Backend Dockerfile — Production-Ready
FROM python:3.11-slim

# Security: run as non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Install system dependencies for OpenCV and other libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p logs uploads temp && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port (Railway sets PORT dynamically)
EXPOSE ${PORT:-8000}

# Health check (uses PORT env var)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/health')" || exit 1

# Start with uvicorn — uses $PORT from Railway (shell form for variable expansion)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --log-level info
