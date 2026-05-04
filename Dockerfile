# Stage 1: Builder
# Using multi-stage build to keep the final image slim and secure
FROM python:3.11-slim AS builder

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed for building certain Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements separately to leverage Docker layer caching
COPY requirements.txt .

# Install dependencies to a local directory
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Final Production Image
FROM python:3.11-slim

# Re-declare ENV variables for the final stage
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app

WORKDIR /app

# Install runtime system dependencies (OpenCV headless and libmagic for file type detection)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# Copy installed packages from the builder stage
COPY --from=builder /root/.local /home/appuser/.local
RUN chown -R appuser:appuser /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Create necessary runtime directories
RUN mkdir -p logs uploads temp && chown -R appuser:appuser /app/logs /app/uploads /app/temp

# Switch to the non-root user
USER appuser

# Expose port (Railway/PaaS providers set PORT dynamically)
EXPOSE 8000

# Robust Health Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request; \
    port = os.environ.get('PORT', '8000'); \
    try: urllib.request.urlopen(f'http://localhost:{port}/health'); \
    except: exit(1)"

# Start the application
# Using python app/main.py as it handles the dynamic PORT logic internally
CMD ["python", "app/main.py"]
