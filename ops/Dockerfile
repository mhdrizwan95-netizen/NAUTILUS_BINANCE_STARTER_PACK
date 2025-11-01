FROM python:3.11.9-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip && \
    pip install --prefix=/install \
      httpx>=0.27 \
      requests>=2.32 \
      pandas>=2.2 \
      numpy>=1.24 \
      pyarrow>=14.0 \
      prometheus-client>=0.20

FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY ops/ ./ops/

RUN useradd -r -u 1000 appuser \
 && chown -R appuser:appuser /app

USER appuser

ENV ENGINE_URL=http://engine_binance:8003 \
    ENABLE_EXECUTION=true \
    PROBE_USDT=30 \
    MAX_SLIP_BP=120 \
    MAX_ORDERS_PER_MIN=20 \
    MAX_PARALLEL_ORDERS=3 \
    PROBE_COOLDOWN_SEC=90

CMD ["python","-u","ops/main.py"]
