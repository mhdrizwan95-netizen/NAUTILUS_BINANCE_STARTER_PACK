# System Design

Nautilus HMM is organised as a layered trading stack: a lean execution engine, an opinionated strategy runtime, an operations control plane, and an observability bundle. This document describes how the layers interact, where state lives, and how data flows from a trading signal to monitoring dashboards.

```
                 ┌────────────────────────────┐
                 │  Strategy / ML Layer       │
Signals & alpha  │  engine/strategy.py        │
  ─────────────▶ │  strategies/policy_hmm.py  │
                 └────────────┬───────────────┘
                              │ POST /orders
                              ▼
                 ┌────────────────────────────┐
                 │ Execution Engine            │
                 │ engine/app.py               │
                 │ OrderRouterExt + RiskRails  │
                 └────────────┬───────────────┘
                              │ venue client
                              ▼
                 ┌────────────────────────────┐
                 │ Exchange + Portfolio        │
                 │ Portfolio.apply_fill        │
                 │ SnapshotStore + SQLite      │
                 └────────────┬───────────────┘
                              │ metrics + events
                              ▼
                 ┌────────────────────────────┐
                 │ Ops / Governance Layer      │
                 │ ops/ops_api.py + daemons    │
                 └────────────┬───────────────┘
                              │ Prometheus scrape
                              ▼
                 ┌────────────────────────────┐
                 │ Observability & Dashboards  │
                 │ Prometheus + Grafana        │
                 └────────────────────────────┘
```

## 1. Execution Plane (engine/)

### Entry points
- `engine/app.py` hosts a FastAPI application with REST endpoints (`/orders/*`, `/reconcile/manual`, `/metrics`, `/readyz`, `/version`).
- Startup hooks initialise balances, load snapshots, schedule the strategy loop, and kick off reconciliation/background refresh tasks.
- Shutdown closes venue clients cleanly.

### Order lifecycle
1. A request reaches `/orders/market` or `/orders/limit`.
2. `RiskRails.check_order` (`engine/risk.py`) enforces trading toggles, symbol allowlists, notional bounds, exposure caps, rate limits, and venue error breakers.
3. The order is normalised (`symbol.VENUE`) and passed to `OrderRouterExt` (`engine/core/order_router.py`).
4. `OrderRouterExt` selects the appropriate venue client and submits the order:
   - `BinanceREST` (`engine/core/binance.py`) for Binance spot/futures.
   - `KrakenREST` (`engine/core/kraken.py`) for Kraken Futures.
   - `IbkrClient` (`engine/connectors/ibkr_client.py`) for equities via TWS/Gateway.
   - Any other venue (e.g. Bybit) currently falls back to the Binance client; a dedicated adapter is required before production use.
5. Successful fills update the in-memory `Portfolio` (`engine/core/portfolio.py`), which maintains cash, equity, exposure, realised/unrealised PnL, and per-symbol positions.
6. `metrics.update_portfolio_gauges` (`engine/metrics.py`) refreshes Prometheus gauges; counters for submitted, rejected, and filled orders tick at each stage.
7. The order and fill are appended to JSONL logs (`engine/idempotency.append_jsonl`) and persisted asynchronously to SQLite (`engine/storage/sqlite.py`).

### Resilience features
- **SnapshotStore** (`engine/state.py`) persists portfolio snapshots atomically so the engine can restore state on startup.
- **Idempotency** (`engine/idempotency.py`) deduplicates requests via the `X-Idempotency-Key` header with a persisted TTL cache.
- **Reconciliation** (`engine/reconcile.py` + `engine/core/reconcile_daemon.py`) back-fills fills from venue APIs since the last snapshot.
- **Event bus** (`engine/core/event_bus.py`) provides async pub/sub hooks for order, risk, strategy, and metrics events.
- **SQLite store** (`engine/storage/sqlite.py`) keeps orders, fills, positions, and equity snapshots with a background flush thread.

## 2. Strategy & ML Layer

### Built-in strategy loop
- `engine/strategy.py` starts a background thread (configurable via `STRATEGY_ENABLED`, `STRATEGY_DRY_RUN`, `STRATEGY_INTERVAL_SEC`, etc.).
- For each configured symbol (`STRATEGY_SYMBOLS` or risk config), it:
  - Fetches a latest price via Binance public endpoints.
  - Updates the moving-average crossover model (`_MACross`).
  - Streams ticks into the HMM policy ingestion (`strategies/policy_hmm.py`).
  - Optionally evaluates the HMM model (lazy-loaded pickle under `engine/models/active_hmm_policy.pkl`).
  - Combines MA and HMM signals via `strategies/ensemble_policy.py` with confidence thresholds.
  - Emits orders through `post_strategy_signal`, which reuses the REST router path with risk checks and idempotency.
- A lightweight bracket watcher can place TP/SL follow-up orders while the HMM mode is enabled.

### External models
- `ml_service/app.py` exposes `/train`, `/partial_fit`, `/infer`, `/infer_h2`, and model registry endpoints. It is not included in the default compose file; run it manually with `uvicorn ml_service.app:app`.
- Offline training, evaluation, and governance helpers live under `scripts/` and `pipeline/` (e.g. `scripts/train_hmm_policy.py`, `scripts/backtest_hmm.py`, `pipeline/train_bandit_offline.py`).
- The executor (`ops/main.py trade`) can act as an alternative signal generator that calls the engine REST API directly, using volatility-aware sizing and slippage heuristics.

### Risk integration
- All strategy-originated orders go through `RiskRails` before being sent.
- Strategy signals support `dry_run` mode to log intent without routing live orders (`STRATEGY_DRY_RUN=true`).

## 3. Ops & Governance Layer (ops/)

### Ops API (`ops/ops_api.py`)
- FastAPI app exposing control endpoints: `/status`, `/kill`, `/strategy/*`, `/metrics`, `/metrics_snapshot`, `/aggregate/*`, SSE/WebSocket feeds, and telemetry ingestion.
- Aggregates metrics from engines, executor, universe, and screener, using `ops/prometheus.py` for multi-process safe counters and gauges.
- Requires `X-OPS-TOKEN` for mutating actions (`OPS_API_TOKEN`, default `dev-token`).

### Governance & automation
- `ops/strategy_router.py` routes strategy signals with weightings and tags.
- `ops/capital_allocator.py` adjusts per-model capital quotas based on performance metrics.
- `ops/exposure_collector.py`, `ops/aggregate_exposure.py`, and `ops/pnl_collector.py` consolidate venue/account telemetry.
- `ops/governance_daemon.py`, `ops/m20_playbook.py`, `ops/m25_governor.py`, and related scripts implement policy enforcement, playbooks, and compliance workflows.
- Supporting JSON/YAML configs (`ops/strategy_weights.json`, `ops/capital_policy.json`, `ops/policies.yaml`, `ops/capital_allocations.json`) drive governance logic.

### Supporting microservices
- `universe/service.py` maintains symbol buckets via exchange info and exposes `/universe`, `/tick`, and Prometheus metrics.
- `situations/service.py` evaluates feature payloads against rules, tracks novelty, and emits metrics and events.
- `screener/service.py` fetches klines/order books, computes alpha scores, forwards hits to situations, and exports scan metrics.

## 4. Observability & Persistence

### Metrics
- `engine/metrics.py` defines counters/gauges/histograms for orders, fees, exposure, mark prices, reconciliation lag, error rates, and submit-to-ack latency.
- `ops/prometheus.py` coordinates a shared multiprocess registry so multiple Uvicorn workers can publish metrics safely.
- Exporters (`hmm_engine_*_exporter`) expose the same `/metrics` surface without trading capabilities for secure scraping.

### Logging & storage
- Orders and fills append to `engine/logs/orders.jsonl`, `engine/logs/events.jsonl`, etc. using atomic writes.
- SQLite (`data/runtime/trades.db`) captures orders/fills/positions/equity snapshots for audit and analytics.
- Snapshot files (`engine/state/portfolio.json`) ensure restart continuity.
- The idempotency cache persists to `engine/state/idempotency_cache.json`.

### Observability bundle
- `ops/observability/docker-compose.observability.yml` provisions Prometheus, Grafana, Loki, and Promtail on the shared `nautilus_trading_network`.
- Dashboards live under `ops/observability/grafana/dashboards/`; Prometheus rules under `ops/observability/prometheus/rules/`.
- `ops/observability/validate_obs.sh` runs scripted PromQL checks against Prometheus.
- `docs/network-dns-fix.md` documents networking requirements (e.g., exporters and Prometheus must share the same Docker network for DNS resolution).

## 5. Data & Event Flow

1. **Signal generation**: built-in scheduler, external ML service, or executor produces a `StrategySignal`.
2. **Risk gating**: `RiskRails.check_order` enforces toggles, limits, breakers.
3. **Order routing**: `OrderRouterExt` normalises symbols, rounds quantities, queries venue specs, submits via venue client.
4. **Persistence**: idempotency cache, JSONL log, and SQLite queue capture each order and fill; `Portfolio` updates in-memory state.
5. **Metrics**: Prometheus counters/gauges update immediately; snapshot counter increments on persistence.
6. **Ops aggregation**: Ops API polls exporters/engines, merges metrics, updates dashboards, and feeds governance daemons.
7. **Observability**: Prometheus scrapes exporters, Ops API, universe, situations, and screener; Grafana dashboards visualise trade health.
8. **Governance loop**: capital allocator, canary manager, and policy daemons consume metrics/events and update weights or kill switches.

## 6. Background Jobs & Executors

- `ops/main.py trade` (executor) runs a resilient trading loop with dynamic sizing, slippage guards, and optional TP/SL logic.
- `ops/vol_ranker.py` ranks volatility for symbol selection.
- `ops/scheduler.Dockerfile` builds the backfill service (`backfill`) for periodic dataset refresh.
- `ops/slip_model.py` trains slippage models; `ops/m16_reinforce.py`, `ops/m17_train_*`, `ops/m21_memory_*`, and friends handle reinforcement, hierarchical HMM training, memory lineage, and dream/collective subsystems.

## 7. Configuration Surfaces

| Category | Location | Notes |
|----------|----------|-------|
| Environment | `.env`, `ops/env.*` | Venue credentials, risk knobs, compose wiring. |
| Risk & policies | `engine/policies.yaml`, env vars | Exposure caps, trading toggle, symbol allowlist, min/max notional, breaker thresholds. |
| Strategy defaults | `strategies/policy_hmm/config.py`, env | HMM window, cooldown, TP/SL basis points, ensemble weights. |
| Governance | `ops/capital_policy.json`, `ops/strategy_weights.json`, `ops/capital_allocations.json`, `ops/policies.yaml` | Capital allocation, model weighting, governance rules. |
| Observability | `ops/observability/prometheus/prometheus.yml`, `ops/observability/prometheus/rules/`, `ops/observability/grafana/dashboards/` | Scrape/job targets, alert thresholds, dashboard layouts. |
| Data services | `config/universe.yaml`, `config/screener.yaml`, `config/situations.json` | Universe buckets, screener settings, situation definitions. |
| Logs & persistence | `engine/logs/`, `engine/state/`, `data/runtime/` | JSONL audit logs, snapshots, SQLite database. |

## 8. Constraints & Future Work

- **Bybit:** `engine_bybit` currently reuses the Binance adapter. Implement a dedicated client under `engine/core/` before trading live.
- **ML service:** run manually (not in compose). Ensure `ml_service/model_store/` is mounted/persisted when using auto-promotion flows.
- **IBKR:** requires `ib_insync` and reachable TWS/Gateway. Handle connectivity failures gracefully (`IbkrClient` logs and raises `IBKR_NOT_CONNECTED`).
- **External API limits:** universe/screener services call public endpoints; tune `SCREENER_*` environment variables and watch `screener` metrics for `RATE_LIMIT_429`.
- **Metrics hygiene:** when adding counters/gauges, wire them into `engine/metrics.py` or `ops/prometheus.py` to stay multiprocess-safe.

Keep this document updated as venues, policies, or architecture evolve: each new subsystem should state where it runs, how it persists state, and what metrics/alerts it emits.
