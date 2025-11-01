FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/data_ingester/requirements.txt ./requirements.txt
COPY constraints.txt /constraints.txt
# hadolint ignore=DL3013
RUN pip install --upgrade pip && pip install -c /constraints.txt -r requirements.txt

COPY services/data_ingester/app ./app
COPY services/common /app/common

ENV LEDGER_DB=/shared/manifest.sqlite
ENV DATA_LANDING=/data/incoming
ENV EXCHANGE=binance
ENV SYMBOLS=BTC/USDT,ETH/USDT
ENV TIMEFRAME=1m
ENV BATCH_LIMIT=1000
ENV START_TS=0
ENV END_TS=0
ENV SLEEP_MS=500
ENV LOG_LEVEL=INFO

# Run as non-root user
RUN useradd -m appuser \
    && mkdir -p /data /shared \
    && chown -R appuser:appuser /app /data /shared
USER appuser

EXPOSE 8001

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8001"]
