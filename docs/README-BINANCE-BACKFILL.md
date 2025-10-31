# Binance Historical Backfill

This job pulls historical OHLCV candles from Binance through **CCXT**, writes the files
into `/data/incoming/<symbol>/<timeframe>/`, and registers every chunk in the shared
ledger (`manifest.sqlite`). That means you get the same exactly-once guarantees as the
live ingester: duplicate content is ignored, watermarks enforce progress, and the
training stack can retrain/promote models without seeing the same bar twice.

## How to run

```bash
docker compose \
  -f docker-compose.yml \
  -f compose.autotrain.yml \
  -f compose.backfill.yml \
  run --rm data_backfill
```

The container runs once and exits once it reaches the requested end timestamp.

## Configuration

Edit `.env` or `compose.backfill.yml` to adjust:

- `SYMBOLS` – comma-separated list (`BTC/USDT,ETH/USDT`).
- `TIMEFRAME` – Binance interval (`1m`, `5m`, `1h`, ...).
- `BATCH_LIMIT` – candles per request (respect Binance limits).
- `START_TS` – starting epoch in milliseconds (`0` = use watermark or earliest).
- `END_TS` – stopping epoch in milliseconds (`0` = current time).
- `SLEEP_MS` – additional delay between requests to stay within rate limits.

Set `API_KEY`/`API_SECRET` in the environment if you need authenticated endpoints,
though public OHLCV data works without credentials.

## Why it’s safe

The job uses the same watermark key (`ingest:binance:<symbol>:<timeframe>`) as the
live ingester, so backfills and real-time ingestion never overlap. Each file is stored
with a SHA-256 hash in the ledger; if a file already exists, the duplicate is deleted
immediately. Models that run with `EXACTLY_ONCE=true` will see each bar at most once,
while sliding-window mode (`EXACTLY_ONCE=false`) keeps the statistical efficiency HMMs
like without retraining on duplicate data.
