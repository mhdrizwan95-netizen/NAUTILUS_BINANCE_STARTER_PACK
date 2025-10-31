# Autotrain Stack Overview

The standalone ML overlay has been superseded by the full **autotrain** stack, which owns the end-to-end loop of downloading market data, training HMM regimes, and serving strategy parameters.

Key components now live under `services/`:

- `data_ingester` – scheduled OHLCV downloads with ledger-based dedupe and watermarks.
- `ml_service` – retrains/promotes models exactly once (or sliding window) and hot-reloads for inference.
- `param_controller` – serves contextual presets and records outcomes for continuous tuning.
- `common/manifest.py` – shared SQLite ledger used across the services.

To stand the stack up alongside the existing infrastructure:

```bash
cp .env.example .env          # customise ingestion pairs, scheduler cadence, RBAC, etc.
docker compose -f docker-compose.yml -f compose.autotrain.yml up -d --build
```

All services share the `data`, `models`, and `shared` volumes defined in `compose.autotrain.yml`. Ports:

- `8001` → data ingester API (`/health`, `/ingest_once`)
- `8002` → parameter controller (`/health`, `/param/...`, `/learn/outcome/...`)
- `8003` → ML service (`/health`, `/train`, `/predict`, `/model`)

For a soup-to-nuts runbook—covering ledger semantics, strict vs sliding windows, parameter schemas, and promotion policy—see `docs/AUTOTRAIN_IMPLEMENTATION_GUIDE.md`.
