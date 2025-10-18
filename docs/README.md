# Nautilus HMM • System Overview

Nautilus HMM combines an exchange-facing execution engine, an operational control plane, ML services, and an offline research pipeline. This document is the codebase map—use it to jump to the right module and to understand how pieces collaborate at runtime.

---

## Stack At A Glance

| Area | What lives here | Key entry points |
|------|-----------------|------------------|
| **Execution engines** | FastAPI services for venue connectivity, risk, reconciliation, Prometheus export | `engine/app.py`, `engine/core/*`, `engine/metrics.py` |
| **Operational control** | Ops API, strategy routing, capital allocator, governance loops, dashboards | `ops/ops_api.py`, `ops/strategy_router.py`, `ops/capital_allocator.py`, `ops/pnl_dashboard.py` |
| **Observability** | Multiprocess Prometheus registry, scrape/alert bundles, Grafana dashboards | `ops/prometheus.py`, `ops/observability/*`, `ops/prometheus.yml` |
| **Automation & executors** | Auto-probing trade loop, schedulers, operational scripts | `ops/main.py`, `ops/auto_probe.py`, `ops/vol_ranker.py`, `scripts/*` |
| **Strategy & ML** | HMM policy implementation, telemetry, guardrails, online/offline training services | `strategies/hmm_policy/*`, `ml_service/app.py`, `ops/m16_reinforce.py` |
| **Research & data** | Feature builders, simulation pipeline, raw/derived datasets, notebooks | `pipeline/*`, `adapters/*`, `data/`, `reports/`, `notebooks/` |

---

## Codebase Layout

| Path | Purpose | Highlights |
|------|---------|------------|
| `engine/` | Runtime execution service | `engine/app.py`, `engine/risk.py`, `engine/metrics.py`, `engine/state.py` |
| `engine/core/` | Venue adapters, portfolio, order routing, reconciliation | `engine/core/order_router.py`, `engine/core/binance.py`, `engine/core/event_bus.py` |
| `ops/` | Ops API, collectors, governance jobs, dashboards | `ops/ops_api.py`, `ops/prometheus.py`, `ops/pnl_dashboard.py`, `ops/governance_daemon.py` |
| `ops/observability/` | Stand-alone Prometheus/Grafana bundle | `ops/observability/docker-compose.observability.yml`, `ops/observability/prometheus/rules/*.yml` |
| `strategies/hmm_policy/` | Production HMM strategy implementation | `strategies/hmm_policy/strategy.py`, `strategies/hmm_policy/features.py`, `strategies/hmm_policy/guardrails.py` |
| `ml_service/` | FastAPI ML microservice with model registry | `ml_service/app.py` |
| `pipeline/` | Offline feature, simulation, reporting scripts | `pipeline/build_features.py`, `pipeline/sim_exec.py`, `pipeline/train_bandit_offline.py` |
| `adapters/` | Exchange data ingestion utilities | `adapters/binance_hist.py`, `adapters/account_provider.py` |
| `universe/`, `situations/`, `screener/` | Supporting APIs served via compose | `universe/service.py`, `situations/service.py`, `screener/service.py` |
| `scripts/` | Operational helpers and automation | `scripts/auto_promote_if_better.py`, `scripts/model_registry.py` |
| `docs/` | Handbooks and design docs | `docs/OPS_RUNBOOK.md`, `docs/DEV_GUIDE.md`, `docs/SYSTEM_DESIGN.md` |
| `config/` | Declarative configuration snippets | `config/universe.yaml`, `config/screener.yaml`, `config/situations.json` |

---

## Runtime Services

| Component | Container | Host port(s) | Notes |
|-----------|-----------|--------------|-------|
| Ops API & control plane | `hmm_ops` | `8002` | FastAPI app in `ops/ops_api.py`; serves governance APIs, dashboards, `/metrics` |
| Binance engine (trader) | `hmm_engine_binance` | `8003` | Exchange execution with live risk rails and metrics |
| Binance engine (exporter) | `hmm_engine_binance_exporter` | `9103` | Read-only exporter focused on scraping-safe metrics |
| Bybit engine | `hmm_engine_bybit` | `8004` | Shares engine code with venue overrides and env file in `ops/env.bybit` |
| IBKR engine | `hmm_engine_ibkr` | `8005` | Leverages `engine/connectors/ibkr_client.py` when credentials supplied |
| Executor / auto-probe | `hmm_executor` | `9102` | Runs `ops/main.py trade`; storm-resistant probing loop |
| Situations API | `hmm_situations` | `8011` | Serves situational analytics from `situations/service.py` |
| Universe API | `hmm_universe` | `8009` | Exposes tradable universe via `universe/service.py` |
| Screener API | `hmm_screener` | `8010` | Factor screening service depending on universe and situations |
| ML service (optional) | `ml_service` | `8010` (default) | Hierarchical HMM trainer/inferencer (`ml_service/app.py`) when launched |
| Prometheus (optional) | `hmm_prometheus` | `9090` | Uses `ops/observability/prometheus/prometheus.yml` |
| Grafana (optional) | `hmm_grafana` | `3000` | Dashboards in `ops/observability/grafana/dashboards/` auto-provision |
| Backfill scheduler | `hmm_backfill` | - | Runs continuous dataset refresh via `ops/scheduler.Dockerfile` |
| Volatility ranker / slip trainer | `hmm_vol_ranker`, `hmm_slip_trainer` | - | Background research daemons in `ops/` |

Bring services up with `docker compose up` for the core stack and `docker compose -f ops/observability/docker-compose.observability.yml up` for observability extras.

---

## Trade Lifecycle

1. **Signal intake** – Control-plane clients call strategy endpoints on `ops/ops_api.py`; requests are authenticated and normalized.
2. **Model routing** – `ops/strategy_router.py` selects a model using weighted routing, enforces USD quotas from `ops/capital_allocator.py`, and records the decision.
3. **Engine submission** – The enriched order is forwarded to `/orders/*` on the relevant engine (`engine/app.py`), where `engine/risk.py` applies notional, exposure, and rate guards.
4. **Venue execution** – `engine/core/order_router.py` resolves venue clients (`engine/core/binance.py`, `engine/connectors/ibkr_client.py`) and applies fees, sizing, and rounding.
5. **State persistence & reconciliation** – Fills update `engine/core/portfolio.py`, persist via `engine/state.py`, and are cross-checked by `engine/reconcile.py` and `engine/core/reconcile_daemon.py`.
6. **Events & metrics** – Order outcomes publish on the async bus (`engine/core/event_bus.py`), gauges/counters in `engine/metrics.py` refresh, and append-only audit logs (`engine/idempotency.py`) capture payloads.
7. **Governance feedback** – Ops collectors (`ops/pnl_collector.py`, `ops/exposure_collector.py`) ingest engine metrics, update the telemetry snapshot, and feed governance/allocator loops.

---

## Control Plane Internals

- **Ops API** (`ops/ops_api.py`) mounts routers for orders, strategies, PnL dashboards, and situations. It serves `/metrics`, `/status`, SSE/WebSocket streams, and guarded admin endpoints such as `/kill` and `/retrain`.
- **Strategy router** (`ops/strategy_router.py`) implements weighted routing, quota enforcement, audit logging, and engine failover using shared HTTPX clients.
- **Capital allocator** (`ops/capital_allocator.py`) parses Prometheus exposition, falls back to `ops/strategy_registry.json`, recalculates USD budgets, and persists them atomically to `ops/capital_allocations.json`.
- **Governance & policy loops** (`ops/governance_daemon.py`, `ops/m16_reinforce.py`) monitor strategy health, enforce YAML/JSON policies, and can hot-promote models by hitting `engine/app.py:/strategy/promote`.
- **Executor & auto-probe** (`ops/main.py`, `ops/auto_probe.py`) provide a storm-resistant trading loop with circuit breakers, rate limiting, slip estimation, and shared price caches; `hmm_executor` runs this mode.
- **Situational services** (`situations/service.py`, `universe/service.py`, `screener/service.py`) back dashboards with curated context, symbol universes, and factor data sourced from `config/` and `data/`.
- **Telemetry store** (`ops/telemetry_store.py`) offers a multiprocess-safe snapshot persisted for dashboards and as a metrics fallback when Prometheus is down.

---

## Execution Engine Internals

- **FastAPI entrypoint** (`engine/app.py`) wires risk rails, exchange clients, strategy router, Prometheus export, background tasks (spec refresh, reconciliation, governance hooks), and SSE streaming.
- **Risk rails** (`engine/risk.py`) enforce trading toggles, per-symbol/total exposure caps, notional bounds, and venue error breakers, emitting gauges such as `breaker_state`.
- **Order routing** (`engine/core/order_router.py`, `engine/core/order_router_ext.py`) handles quote→quantity conversion, venue-specific guards, fee calculations, and portfolio updates.
- **Exchange adapters** (`engine/core/binance.py`, `engine/connectors/ibkr_client.py`, `engine/core/venue_specs.py`) encapsulate REST signing, futures hedge mode support, and symbol metadata caching.
- **State & reconciliation** (`engine/state.py`, `engine/reconcile.py`, `engine/core/reconcile_daemon.py`) persist snapshots under `engine/state/`, restore on startup, and continuously reconcile venue fills.
- **Strategy integration** (`engine/strategy.py`, `strategies/hmm_policy/strategy.py`) embeds Nautilus strategies inside the engine with optional schedulers and hot-reload hooks.
- **Event bus & alerting** (`engine/core/event_bus.py`, `engine/core/alert_daemon.py`) broadcast order/risk/governance events consumed by Ops SSE streams and alert pipelines.
- **Prometheus metrics** (`engine/metrics.py`) define counters, gauges, and histograms shared across workers and exposed via `/metrics` using a multiprocess-safe registry.

---

## Strategy & ML Stack

- **HMM policy** (`strategies/hmm_policy/`) contains feature engineering, macro/micro state tracking, guardrails, telemetry publishing, and the Nautilus `TradingStrategy` subclass.
- **ML microservice** (`ml_service/app.py`) manages model versioning, hierarchical HMM fitting, partial updates, blue/green deployment tags, and inference endpoints (`/infer`, `/infer_h2`, `/train`).
- **Feedback & reinforcement** (`ops/m16_reinforce.py`, `strategies/hmm_policy/feedback.py`) orchestrate reinforcement learning signals and policy updates tied into Ops governance.
- **Promotion scripts** (`scripts/auto_promote_if_better.py`, `scripts/model_registry.py`) automate canary evaluation, promotion, and registry reporting through the Ops API.

---

## Research & Data Pipeline

- **Adapters** (`adapters/binance_hist.py`, `adapters/ibkr_hist.py`) download historical venue data into `data/raw/...`.
- **Offline pipeline** (`pipeline/`) generates features (`build_features.py`), replays situations, simulates execution (`sim_exec.py`), trains bandits, and produces reports (`report_backtest.py`). Make targets (`features`, `simulate`, `report`) wrap these flows.
- **Data lake** (`data/`) stores raw klines, engineered features, outcomes, and model artifacts consumed by both live and offline processes.
- **Tooling** under `backtests/`, `situations/`, `screener/`, `universe/`, `notebooks/`, and `reports/` enables exploratory analysis, dashboard exports, and governance review packages.

---

## Observability & Metrics

- **Multiprocess registry** (`ops/prometheus.py`) coordinates Prometheus shard files (`PROMETHEUS_MULTIPROC_DIR`), performs cleanup on startup, and powers `/metrics` for `hmm_ops`.
- **Engine metrics** (`engine/metrics.py`) expose portfolio gauges, order counters, latency histograms, and per-symbol series consumed by dashboards and alerting rules.
- **Prometheus bundle** (`ops/observability/`) provides a dedicated compose file, curated scrape configs (`ops/observability/prometheus/prometheus.yml`), and alert/recording rules (`ops/observability/prometheus/rules/*.yml`).
- **Grafana** is provisioned automatically via `ops/observability/grafana/provisioning/` and ships dashboards such as `ops/observability/grafana/dashboards/venue_binance.json`.
- **Alerting** leverages rule groups for breaker activity, latency, reject rates, and mark freshness; extend them in `ops/observability/prometheus/rules/trading.yml`.
- **Local override** `ops/prometheus.yml` offers a simplified scrape config for ad-hoc metric collection outside the observability bundle.

---

## Automation & Tooling

- **Compose & Docker** – `docker-compose.yml` orchestrates the full stack; `Dockerfile`, `ops/Dockerfile`, and `ops/scheduler.Dockerfile` build runtime, executor, and scheduled worker images.
- **Make targets** (`Makefile`) bootstrap dependencies, start/stop the stack, probe symbols, and run the offline research pipeline.
- **Utility scripts** (`scripts/`, `ops/*.py`) cover governance automation, slip model training, volatility ranking, backtesting, and operational tasks.
- **Testing & packaging** – `pyproject.toml`, `requirements.txt`, and `requirements-dev.txt` define runtime/dev dependencies; `tests/` houses unit and integration coverage.
- **Frontend assets** – `frontend/` and `dashboard/` include UI components consumed by the Ops dashboard and the React frontend.

---

## Configuration Surfaces

- **Environment files** – `.env` (copy from `env.example`) drives Docker compose; venue-specific overrides live in `ops/env.*`.
- **Risk & governance** – `engine/policies.yaml`, `ops/capital_policy.json`, `ops/strategy_weights.json`, and `ops/capital_allocations.json` codify trade limits and capital distribution.
- **Universe & situations** – `config/universe.yaml`, `config/situations.json`, and `config/screener.yaml` seed the supporting APIs; `strategies/hmm_policy/config.py` defines strategy defaults.
- **Metrics & alerts** – Adjust scrape targets in `ops/observability/prometheus/prometheus.yml` or local `ops/prometheus.yml`; tune alert thresholds in `ops/observability/prometheus/rules/`.
- **Secrets** – Venue and broker credentials (`BINANCE_API_KEY`, `IBKR_USERNAME`, etc.) are injected via environment variables referenced in compose definitions.

---

## Next Steps

- Operators: start with `docs/OPS_RUNBOOK.md` for on-call procedures, playbooks, and escalation paths.
- Developers: follow `docs/DEV_GUIDE.md` for workflow conventions, testing strategy, and coding patterns.
- Architects: see `docs/SYSTEM_DESIGN.md` for deeper diagrams, control-flow details, and governance philosophy.
- Deployment walkthroughs: `NAUTILUS_BINANCE_STEP_BY_STEP.md` and `README_DEPLOYMENT.md` provide zero-to-one environment setup guidance.

Happy shipping—keep Grafana open to watch the HMM stack adapt in real time.
