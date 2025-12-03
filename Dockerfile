# Builder stage: install deps with build tooling
FROM python:3.11.9-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --prefix=/install -r requirements.txt

# Build the React/TypeScript Command Center bundle
FROM node:20-bookworm-slim AS frontend_builder
WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Runtime stage
FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPS_BASE="http://ops:8001" \
    DASH_BASE="http://dash:8002" \
    PROMETHEUS_MULTIPROC_DIR="/tmp/prom_multiproc"

WORKDIR /app

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Copy code
COPY . .

# Drop the prebuilt Command Center assets into the ops static directory
COPY --from=frontend_builder /frontend/build /app/ops/static_ui

# Non-root user
RUN useradd -m appuser \
    && mkdir -p /tmp/prom_multiproc \
    && chown appuser:appuser /tmp/prom_multiproc \
    && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","engine.app:app","--host","0.0.0.0","--port","8003"]
