# Documentation Index

## Orientation

- **Overview:** `../README.md` summarises services, launch steps, and observability.
- **Architecture:** `SYSTEM_DESIGN.md` explains engine internals, event flow, storage, and governance loops.
- **Development:** `DEV_GUIDE.md` covers local setup, testing strategy, and style conventions.
- **Operations:** `OPS_RUNBOOK.md` provides daily checks, recovery playbooks, and emergency procedures.

## Module Map

| Area | Scope | Notable entry points |
|------|-------|----------------------|
| Execution engine | FastAPI order API, risk rails, persistence, reconciliation, metrics | `engine/app.py`, `engine/core/order_router.py`, `engine/risk.py`, `engine/metrics.py`, `engine/storage/sqlite.py` |
| Strategy runtime | Built-in MA + HMM ensemble, policy wiring, scheduler loop | `engine/strategy.py`, `strategies/policy_hmm.py`, `strategies/ensemble_policy.py` |
| Machine learning & research | Model registry, hierarchical HMM training, replay/backtests, notebooks | `ml_service/app.py`, `ml_service/hierarchical_hmm.py`, `scripts/train_hmm_policy.py`, `pipeline/*`, `notebooks/*` |
| Ops & governance | Ops API, capital allocator, exposure collectors, governance daemons | `ops/ops_api.py`, `ops/strategy_router.py`, `ops/capital_allocator.py`, `ops/exposure_collector.py`, `ops/governance_daemon.py` |
| Observability | Prometheus registry, dashboards, alert rules, validation tooling | `ops/prometheus.py`, `ops/observability/docker-compose.observability.yml`, `ops/observability/prometheus/rules/*.yml`, `ops/observability/validate_obs.sh` |
| Supporting services | Tradable universe, situation detection, screener scanning | `universe/service.py`, `situations/service.py`, `screener/service.py` |
| Executors & tooling | Trade executors, probes, calibration and governance scripts | `ops/main.py`, `ops/auto_probe.py`, `ops/vol_ranker.py`, `ops/m16_reinforce.py`, `scripts/*` |
| Persistence & idempotency | Snapshot store, SQLite ingestion, deduplication cache, logs | `engine/state.py`, `engine/storage/sqlite.py`, `engine/idempotency.py`, `engine/logs/` |

The `engine_bybit` service reuses the generic engine image with `VENUE=BYBIT`; a dedicated adapter will live under `engine/core/` once implemented, so treat Bybit as experimental until then.

## Document Set

- `SYSTEM_DESIGN.md` — layered architecture, execution flow, metrics, fault tolerance, and scaling notes.
- `DEV_GUIDE.md` — environment bootstrap, coding guidelines, testing expectations, instrumentation, and dependency management.
- `OPS_RUNBOOK.md` — checklists for routine operations, troubleshooting, governance controls, and incident response.
- `network-dns-fix.md` — DNS incident write-up for the Kraken exporter/Prometheus scrape path.
- `hmm_operator_handbook.md` — ML operator and calibration procedures for the HMM stack.
- `NAUTILUS_BINANCE_STEP_BY_STEP.md` — step-by-step deployment walkthrough with screenshots.
- `README_DEPLOYMENT.md` — calibration, reinforcement, memory, guardian, and collective intelligence subsystems.

## Configuration Surfaces

- Environment: `.env` (copy from `env.example`) plus venue overrides in `ops/env.*`.
- Risk rails: environment variables (`MIN_NOTIONAL_USDT`, `MAX_ORDERS_PER_MIN`, `TRADE_SYMBOLS`, etc.) and `engine/policies.yaml`.
- Governance inputs: `ops/capital_policy.json`, `ops/strategy_weights.json`, `ops/capital_allocations.json`, `ops/policies.yaml`.
- Observability: `ops/observability/prometheus/prometheus.yml`, `ops/observability/grafana/dashboards/`, `ops/observability/prometheus/rules/`.
- Supporting services: configuration under `config/` (universe buckets, screener settings, situation definitions).
- State & logs: `engine/state/portfolio.json`, `engine/logs/orders.jsonl`, `data/runtime/trades.db`, `ops/exports/`, `data/memory_vault/`.

## Daily References

- `Makefile` — `make help` lists lifecycle, observability, and autopilot targets.
- Metrics — scrape exporters (`hmm_engine_*_exporter`) and Ops API (`/metrics`, `/metrics_snapshot`).
- Control endpoints — kill switch (`POST /kill`), strategy routing (`/strategy/*`), reconciliation (`/reconcile/manual`), executor toggles (`ops/main.py` CLI).
- Health checks — `GET /readyz` (Ops), `GET /health` (engines), Prometheus `/targets`, Grafana dashboards.

Keep this index aligned with reality whenever services, policies, or procedures change. If you add a subsystem, update the table above and cross-link the relevant documentation.
