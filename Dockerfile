# Stage 1: Builder
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

COPY --from=builder /root/.local /home/appuser/.local
RUN chown -R appuser:appuser /home/appuser/.local

COPY --chown=appuser:appuser . .

RUN mkdir -p logs uploads temp && chown -R appuser:appuser /app

USER appuser

# Health check (uses Railway dynamic PORT)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
CMD python -c "import os,urllib.request; \
port=os.environ.get('PORT'); \
urllib.request.urlopen(f'http://127.0.0.1:{port}/health')"

# ✅ IMPORTANT: Use Railway PORT ONLY (no fallback)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT --log-level info --timeout-keep-alive 65"]