# Documentation Index

## Orientation

- Overview: `PROJECT_OVERVIEW.md` and `../README.md` summarise services, launch steps, and observability.
- Architecture: `SYSTEM_DESIGN.md` explains engine internals, event flow, storage, and governance loops.
- Development: `DEV_GUIDE.md` covers local setup, testing strategy, and style conventions.
- Operations: `OPS_RUNBOOK.md` provides daily checks, recovery playbooks, and emergency procedures.

## Module Map

| Area | Scope | Notable entry points |
|------|-------|----------------------|
| Execution engine | FastAPI order API, risk rails, persistence, reconciliation, metrics | `engine/app.py`, `engine/core/order_router.py`, `engine/risk.py`, `engine/metrics.py`, `engine/storage/sqlite.py` |
| Strategy runtime | Built-in MA + HMM ensemble, tick strategies, event-driven modules | `engine/strategy.py`, `engine/strategies/policy_hmm.py`, `engine/strategies/trend_follow.py`, `engine/strategies/listing_sniper.py` |
| Machine learning & research | Model registry, hierarchical HMM training, replay/backtests, notebooks | `ml_service/app.py`, `scripts/train_hmm_policy.py`, `pipeline/*`, `notebooks/*` |
| Ops & governance | Ops API, capital allocator, exposure collectors, governance daemons | `ops/ops_api.py`, `ops/strategy_router.py`, `ops/capital_allocator.py`, `ops/exposure_collector.py` |
| Observability | Prometheus registry, dashboards, alert rules, validation tooling | `ops/observability/docker-compose.observability.yml`, `ops/observability/prometheus/rules/*.yml`, `ops/observability/validate_obs.sh` |
| Supporting services | Tradable universe, situation detection, screener scanning | `universe/service.py`, `situations/service.py`, `screener/service.py` |
| Persistence & idempotency | Snapshot store, SQLite ingestion, deduplication cache, logs | `engine/state.py`, `engine/storage/sqlite.py`, `engine/idempotency.py`, `engine/logs/` |

## Curated document set

- `PROJECT_OVERVIEW.md` — mission, current snapshot, and open venue roadmap.
- `SYSTEM_DESIGN.md` — layered architecture, execution flow, and fault-tolerance patterns.
- `DEV_GUIDE.md` — environment bootstrap, coding standards, testing expectations, and instrumentation.
- `OPS_RUNBOOK.md` — daily health checks, incident recovery, governance controls, and escalation paths.
- `OBSERVABILITY.md` — Prometheus/Grafana topology, alerting rules, and validation tooling.
- `FEATURE_FLAGS.md` — risk gates and feature toggles with recommended defaults.
- `ML_SERVICE_INTEGRATION.md` — autotrain stack quick start, ledger semantics, and operational guardrails.
- `BACKTEST_SUITE_GUIDE.md` — prequential simulation workflow, quick start, and extension hooks.
- `README-BINANCE-BACKFILL.md` — historical backfill job covering configuration and safety notes.

## Daily References

- `Makefile` — `make help` lists lifecycle, observability, and autopilot targets.
- Metrics — scrape exporters (`hmm_engine_*_exporter`) and Ops API (`/metrics`, `/metrics_snapshot`).
- Control endpoints — kill switch (`POST /kill`), strategy routing (`/strategy/*`), reconciliation (`/reconcile/manual`).
- Health checks — `GET /readyz` (Ops), `GET /health` (engines), Prometheus `/targets`, Grafana dashboards.

Keep this index aligned with reality whenever services, policies, or procedures change. If you add a subsystem, update the table above and cross‑link the relevant documentation.
