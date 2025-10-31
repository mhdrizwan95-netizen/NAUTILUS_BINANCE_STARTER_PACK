
# Autotrain Stack — Complete Implementation Guide

This bundle gives you:
- **data_ingester** — downloads new OHLCV bars continuously and records them in a **ledger** (SQLite) with dedup.
- **ml_service** — trains HMMs periodically on newly downloaded data, **promotes** only if validation improves, and **deletes** raw files that were used (optional). It can run in **EXACTLY_ONCE** mode.
- **param_controller** — returns **strategy parameters** dynamically per context and learns from outcomes.

Everything is containerized and wired with a Compose overlay.

---

## 1) Quick Start

```bash
# At repo root
tar -xzf autotrain_stack_bundle.tar.gz
cp .env.example .env  # optional

# Build + run the full stack
docker compose -f docker-compose.yml -f compose.autotrain.yml up -d --build

# Kick the ingester once (it will also be callable via cron or external scheduler):
curl -X POST http://localhost:8001/ingest_once

# Trigger a manual train (dev mode: auth off)
curl -X POST http://localhost:8003/train
```

**Ports**
- `data_ingester`: 8001
- `param_controller`: 8002
- `ml_service`: 8003

---

## 2) Storage & Exactly-Once Semantics

We use a small **ledger** at `/shared/manifest.sqlite` that all services mount.

**What it guarantees**
- Each downloaded file is **content-addressed** (SHA‑256) and recorded with a unique `file_id`.
- The trainer **claims** files atomically (status `downloaded→processing`) and after successful training **marks** them `processed` and **deletes** them if configured.
- Duplicate content is ignored at registration (no double‑count training).
- A per-stream **watermark** (`ingest:<exchange>:<symbol>:<timeframe>`) advances after each successful download so we don’t fetch overlapping ranges.

**Two training modes**

- **Sliding‑window mode** (`EXACTLY_ONCE=false`, default): best for HMM quality. We ensure **no duplicate bars** inside the window, but past bars are **reused** across runs as the window slides. This yields the most stable models.
- **Strict exactly‑once mode** (`EXACTLY_ONCE=true`): each bar is trained **at most once**. The trainer only consumes **new** bars. This avoids any re‑use but is typically **lower quality** for HMMs (no long memory). Use only if you have a compliance requirement to not retain/rehash historical bars.

> Tip: Many teams adopt sliding‑window for the live model and keep *strict mode* for an auxiliary “online” model or for compliance reporting.

---

## 3) Backtesting Reality Check

Does this “fill the backtest gap”? **Not automatically.** You still need a curated **research dataset** to evaluate strategies across many regimes. This stack:
- builds a **clean, deduplicated stream** and can retain either **nothing** (strict deletion) or a **feature store** (extend `ml_service` to materialize features) for research,
- and stores **model versions + metrics** to compare forward performance.

Recommended:
- Run a **separate backfill** job (one‑off) that writes to a **research volume** not subject to deletion.
- Optionally, materialize **features** (returns, vol, spreads) to a Parquet feature store. You can delete raw CSVs while keeping the feature history.

---

## 4) Strategy‑Agnostic Parameter Schemas

Place schema files under `strategy_schemas/`. Examples included:
- `momentum_breakout.yaml`
- `mean_reversion.yaml`
- `pairs_trading.yaml`
- `vwap_participation.yaml`
- `market_making.yaml`
- `trend_following.yaml`

Each schema defines **bounded parameters** and **presets** (safe menu). The **param_controller** chooses a preset per decision, based on context features.

Wire up your trading engine:
1. **Before entry**, call:
   `GET /param/{strategy}/{instrument}?features[hmm_trend]=0.7&features[vol]=0.3&...`
2. Apply returned `params` and tag the order with `config_id`.
3. **After exit**, post outcome:
   `POST /learn/outcome/{strategy}/{instrument}/{preset_id}` with `reward` and `features`.

Start simple (epsilon‑greedy or LinTS). For production, persist posteriors and add guardrails (max changes/day, hysteresis).

---

## 5) Services in Detail

### data_ingester
- **Env**
  - `EXCHANGE` (e.g., `binance`), `SYMBOLS` (comma list, e.g., `BTC/USDT,ETH/USDT`), `TIMEFRAME` (e.g., `1m`), `BATCH_LIMIT` (e.g., 1000), `START_TS` (ms).
- **API**
  - `POST /ingest_once` → downloads the next chunk since watermark, writes CSV under `/data/incoming/<sym>/<tf>/`, registers it in ledger. Duplicate content is auto‑deleted.
- **Retention**
  - Files are deleted by **ml_service** after processing (if `DELETE_AFTER_PROCESS=true`).

### ml_service
- **Scheduler**
  - `ml_scheduler` runs EM retrains via cron (`RETRAIN_CRON`). It claims files from the ledger, trains, **promotes models only on improvement**, and marks/deletes files.
- **Hot‑reload**
  - `ml_service` watches `/models/current` and reloads in‑memory model on promotion.
- **Modes**
  - `EXACTLY_ONCE` vs sliding window as described above.

### param_controller
- **Register menus**
  - `POST /preset/register/{strategy}/{instrument}` body: `{ "preset_id": "p1", "params": { ... } }`
- **Choose params**
  - `GET /param/{strategy}/{instrument}` (+ `features[...]` query)
- **Learn**
  - `POST /learn/outcome/{strategy}/{instrument}/{preset_id}` body: `{ "reward": ..., "features": { ... } }`

---

## 6) Compose Overlay

Use `compose.autotrain.yml` to add the services to your stack. All services share a `shared:` volume for ledgers and controller state.

```bash
docker compose -f docker-compose.yml -f compose.autotrain.yml up -d --build
```

Ensure your trading engine network can reach:
- `ml_service:8000`
- `param_controller:8002`
- `data_ingester:8001` (optional external trigger)

---

## 7) Risk Guardrails (must‑do)

- **RBAC**: enable auth on `ml_service` before exposing `/train` in prod.
- **Rate limits**: param changes ≤ N/day/strategy.
- **Apply to new positions** only; never shock open stops unless it reduces risk.
- **Kill switches**: disable entries if equity drawdown exceeds threshold or daily VAR breached.
- **Promotion gates**: add a walk‑forward P&L gate in addition to the validation metric before promotion.

---

## 8) Runbook

- **Start of day**: ingester watermark verified; schedules set.
- **Every retrain**: metrics logged, version saved; if promoted, watcher reloads.
- **Weekly**: review controller outcomes; prune bad presets; add new presets from offline BO.
- **Monthly**: disaster drill — rollback model via symlink; restore from backup ledgers.

---

## 9) Limitations & Notes

- **HMM incremental training**: `hmmlearn` doesn’t support true partial_fit. Sliding‑window mode is recommended for quality. Strict exactly‑once mode is available but may underperform.
- **Backtesting**: keep a separate, non‑deleted research store if you need long historical tests.
- **Exchanges**: CCXT rate limits apply; consider API keys and backoff for robustness.
