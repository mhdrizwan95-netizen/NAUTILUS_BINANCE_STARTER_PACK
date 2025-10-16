# Multi-arch, small, stable wheels
FROM python:3.11-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for scientific libs & uvloop wheels (slim-friendly)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# Copy code
COPY . .

# Non-root user
RUN useradd -m appuser \
 && mkdir -p /tmp/prom_multiproc \
 && chown appuser:appuser /tmp/prom_multiproc \
 && chown -R appuser:appuser /app
USER appuser

# Default envs; override in compose
ENV OPS_BASE="http://ops:8001" \
    DASH_BASE="http://dash:8002" \
    PROMETHEUS_MULTIPROC_DIR="/tmp/prom_multiproc"

# Uvicorn entrypoints (set by compose)
CMD ["bash","-lc","echo 'Set a command in docker-compose.yml'"]
