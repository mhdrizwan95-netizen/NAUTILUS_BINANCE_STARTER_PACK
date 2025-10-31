# Binance Historical Backfill Job

This job pulls historical OHLCV data from Binance via **CCXT**, writes it into the same
`/data/incoming` landing area used by the live ingester, and registers every chunk in
the shared ledger for exactly-once processing.

## What it does

- Downloads candles for each requested `{symbol, timeframe}` pair in batches.
- Writes CSVs named `SYMBOL__TF__tStart_tEnd.csv` under `/data/incoming/...`.
- Registers each file in `manifest.sqlite` (SHA-256 content key, watermark).
- Advances the watermark so repeated runs resume where they left off.
- Deletes duplicates if the ledger already has the same content.

The `ml_service` scheduler can then pick up the new segments, retrain, and promote
models automatically.

## How to run

```bash
docker compose \
  -f docker-compose.yml \
  -f compose.autotrain.yml \
  -f compose.backfill.yml \
  run --rm data_backfill
```

This is a one-shot job; it exits when it reaches the requested end timestamp.

## Configuration knobs

Set values via `.env` or edit `compose.backfill.yml`:

- `SYMBOLS` – comma list of pairs (`BTC/USDT,ETH/USDT`).
- `TIMEFRAME` – Binance candle interval (`1m`, `5m`, `1h`, ...).
- `START_TS` – ms epoch to start from; `0` falls back to the ledger watermark or the historical earliest.
- `END_TS` – ms epoch to stop at; `0` means “now”.
- `BATCH_LIMIT` – number of candles per request (respect Binance limits).
- `SLEEP_MS` – added delay between requests to reduce rate-limit pressure.

The job uses the same environment variables (`API_KEY`, `API_SECRET`) as the live ingester if you need authenticated endpoints (not required for public OHLCV data).

## Exactly-once guarantees

The ledger (`common/manifest.py`) stores for each file:

- SHA-256 hash → ignores duplicates.
- `{symbol, timeframe, t_start, t_end}` for monitoring.
- Status transitions (`downloaded → processing → processed/deleted`).

The backfill reuses the same watermark naming scheme (`ingest:binance:<symbol>:<timeframe>`), so live ingestion and backfill jobs never overlap or double-train bars.
