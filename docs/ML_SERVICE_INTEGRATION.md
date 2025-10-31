# Autotrain Stack Overview

The autotrain overlay owns the end-to-end ML loop: it acquires market data, retrains HMM regimes, promotes improved checkpoints, and streams strategy parameters back to the engine. The services live under `services/` and are wired in via `compose.autotrain.yml`.

## Quick start

```bash
# At repo root
cp .env.example .env                    # customise symbols, cadences, retention
docker compose \
  -f docker-compose.yml \
  -f compose.autotrain.yml up -d --build

# First ingestion pass
curl -X POST http://localhost:8001/ingest_once

# Manual retrain / promotion trigger (dev mode auth disabled)
curl -X POST http://localhost:8003/train
```

All services share the `data`, `models`, and `shared` volumes declared in the compose overlay. Default ports:

| Service | Port | Key endpoints |
|---------|------|---------------|
| data_ingester | `8001` | `/health`, `/ingest_once` |
| param_controller | `8002` | `/health`, `/param/{strategy}/{instrument}`, `/learn/outcome/...` |
| ml_service | `8003` | `/health`, `/train`, `/predict`, `/model` |

## Component reference

### `data_ingester`
- **Inputs**: `EXCHANGE`, `SYMBOLS`, `TIMEFRAME`, `BATCH_LIMIT`, `START_TS`, `END_TS`, `SLEEP_MS` (configure via `.env`).
- **API**: `POST /ingest_once` downloads the next OHLCV chunk since the watermark, writes a CSV under `/data/incoming/<symbol>/<tf>/`, and registers it in the ledger.
- **Retention**: files are deleted after successful training when `DELETE_AFTER_PROCESS=true` (set on the ML service).

### `ml_service`
- **Scheduler**: the `ml_scheduler` container honours `RETRAIN_CRON` and claims new files from the ledger.
- **Hot reload**: models are symlinked under `/models/current`; the API reloads in-process weights whenever a promotion lands.
- **Training modes**:
  - *Sliding window* (`EXACTLY_ONCE=false`, default): the ledger dedupes bars within the active window but allows historic data to be re-used as the window advances for higher-quality HMMs.
  - *Strict exactly-once* (`EXACTLY_ONCE=true`): every bar is trained at most once. Use only if compliance requires non-reuse—model quality typically suffers without long look-back context.
- **Window blending**: in sliding-window mode the trainer stitches together the latest claimed files with the rolling `TRAIN_WINDOW_DAYS` archive, deduping by timestamp so late-arriving bars overwrite older copies safely.
- **Metadata**: `/train` responses expose `metadata.claimed_files` so you can alert on empty ledger runs and track how much fresh data each job consumed.

### `param_controller`
- **Preset menu**: register safe presets via `POST /preset/register/{strategy}/{instrument}` with a `{ "preset_id": ..., "params": { ... } }` payload.
- **Parameter selection**: `GET /param/{strategy}/{instrument}` (plus `features[...]` query parameters) returns a `config_id` and parameter bundle—the engine should tag orders with the ID.
- **Learning loop**: `POST /learn/outcome/{strategy}/{instrument}/{preset_id}` records realised reward and optional feature context for Thompson Sampling / epsilon-greedy updates.

## Shared ledger & storage semantics

All services mount `/shared/manifest.sqlite`, giving them consistent state:

- Files are **content-addressed** (SHA-256) and stored once. Duplicates are discarded before training.
- A per-stream **watermark** (`ingest:<exchange>:<symbol>:<timeframe>`) ensures backfills and live ingestion never overlap ranges.
- Trainers atomically claim files (`downloaded → processing → processed`) so that concurrent retrains cannot double-consume data.
- If a training run exits early, all claimed file IDs are **requeued** back to `downloaded` so the next cycle can retry without losing coverage.

Recommended practice:

- Keep sliding-window mode for production quality and run a secondary strict model only if auditors require “train once” semantics.
- Run a dedicated backfill job (`compose.backfill.yml`) writing to a research volume if you need long-range historical testing—the production volumes can aggressively delete raw CSVs once features are extracted.

## Parameter schema registry

Declarative menus live under `strategy_schemas/` (for example `momentum_breakout.yaml`, `trend_following.yaml`, `market_making.yaml`). Each schema defines bounds, safe presets, and expected contextual features.

Workflow:

1. Engine calls the parameter controller before submitting an order.
2. Order metadata includes the returned `config_id`.
3. When the trade settles, the engine posts the realised reward to `/learn/outcome/...` so the controller can update its posterior.

Start with the bundled LinTS implementation; persist `A`/`b` matrices per `(strategy, instrument)` for continuity across restarts and enforce policy guardrails (hysteresis, daily limits).

## Compose overlay & connectivity

`compose.autotrain.yml` attaches the services to the main trading network. Ensure the engine references the internal hostnames:

```env
HMM_URL=http://ml_service:8000
PARAM_CONTROLLER=http://param_controller:8002
LEDGER_DB=/shared/manifest.sqlite
```

If you run the stack standalone, expose ports or add an SSH tunnel so that off-host experiments can hit the APIs.

## Operational runbook

- **Start of day:** confirm the ingester watermark advanced, check `/models/registry` for the latest promoted tag, and ensure the scheduler container is healthy.
- **Every retrain:** capture metrics (`metric_name`, `metric_value`), archive the model directory, validate `metadata.claimed_files` is non-zero, and verify the controller reloads the new preset set if applicable.
- **Failure handling:** if a retrain aborts, the dashboard should show the claimed-files count dropping to zero because the trainer requeues the ledger entries; reruns will automatically pick them up.
- **Weekly:** review controller outcome logs; prune underperforming presets and seed new candidates from offline research.
- **Monthly:** rehearse a rollback by repointing the `/models/current` symlink and restoring ledger snapshots from backups.

## Guardrails & limitations

- Protect `/train` and `/preset/register` with auth before exposing them beyond localhost.
- Rate-limit parameter changes (e.g. ≤ N per strategy per day) and apply new presets to **new** positions only.
- Kill-switch the training loop if equity drawdown or model validation metrics breach thresholds.
- `hmmlearn` does not support incremental `partial_fit`; high-quality models still rely on multi-week sliding windows.
- CCXT rate limits apply to the ingester—configure `SLEEP_MS` and API keys accordingly to avoid bans.
