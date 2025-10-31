FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates curl &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY ../common /app/common

ENV LEDGER_DB=/shared/manifest.sqlite
ENV DATA_LANDING=/data/incoming
ENV EXCHANGE=binance
ENV SYMBOLS=BTC/USDT,ETH/USDT
ENV TIMEFRAME=1m
ENV BATCH_LIMIT=1000
ENV START_TS=0
ENV LOG_LEVEL=INFO

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8001"]
