# Nautilus HMM • System Overview

The repository contains a full autonomous trading stack that spans venue engines, an operations control plane, machine-learning workflows, and a first-class observability suite. This document maps the codebase to the running services so you can jump straight to the component you need.

---

## Stack At A Glance

| Area | What lives here | Key entry points |
|------|-----------------|------------------|
| **Trading engines** | Stateless FastAPI apps that talk directly to venues and enforce risk rails | `engine/app.py`, `engine/core/*` |
| **Operations plane** | Aggregation, governance, capital allocation, dashboards, API | `ops/ops_api.py`, `ops/strategy_*`, `ops/capital_allocator.py` |
| **Strategies / ML** | HMM features, online trainer, reinforcement loops | `strategies/hmm_policy/*`, `ops/m16_reinforce.py`, `ml_service/` |
| **Observability** | Prometheus/Grafana bundle, multi-process metrics helpers | `ops/prometheus.py`, `ops/observability/*` |
| **Automation scripts** | Backtests, calibration, deployment utilities | `scripts/*`, `ops/*.sh`, `ops/*.py` |
| **Docs & runbooks** | Ops handbook, dev guide, system design | `docs/*.md`, `OPS_RUNBOOK.md` |

All containers share a single Docker Compose project (`docker-compose.yml`). Optional observability tooling runs from `ops/observability/docker-compose.observability.yml`.

---

## Service Topology & Ports

| Component | Container | Host port | Primary endpoints |
|-----------|-----------|-----------|-------------------|
| Binance engine | `hmm_engine_binance` | `8003` | `/health`, `/orders/*`, `/metrics` |
| Bybit engine | `hmm_engine_bybit` | `8004` → container `8003` | `/health`, `/orders/*`, `/metrics` |
| IBKR engine | `hmm_engine_ibkr` | `8005` → container `8003` | `/health`, `/orders/*`, `/metrics` |
| Ops API | `hmm_ops` | `8002` | `/readyz`, `/metrics`, `/strategy/*`, `/aggregate/*`, `/pnl_dashboard.html` |
| ML service (optional) | `ml_service` | `8010` | `/metrics`, `/train`, `/predict` |
| Prometheus (optional) | `hmm_prometheus` | `9090` | Scrape targets defined in observability pack |
| Grafana (optional) | `hmm_grafana` | `3000` | Pre-provisioned dashboards under “HMM” folder |

All services share the `nautilus_binance_starter_pack_default` Docker network created by `docker compose up`. The observability stack joins the same network automatically.

---

## Quickstart

```bash
git clone <repo>
cd nautilus-hmm/NAUTILUS_BINANCE_STARTER_PACK
cp ops/env.example .env           # set API keys and knobs
docker compose up -d              # launches engines + ops API
```

Verify liveness:

```bash
curl http://localhost:8003/health           # Binance engine
curl http://localhost:8002/readyz           # Ops control plane
curl http://localhost:8002/pnl_dashboard.html
```

Bring up observability (optional but recommended):

```bash
cd ops/observability
docker compose -f docker-compose.observability.yml up -d
open http://localhost:3000          # Grafana (admin / admin)
open http://localhost:9090          # Prometheus UI
```

---

## Metrics & Observability

### Multi-process Prometheus registry

Uvicorn runs the OPS API with multiple workers. All OPS-side collectors register against `ops/prometheus.py`, which:

* Creates a per-process `CollectorRegistry` and attaches `prometheus_client.multiprocess.MultiProcessCollector`.
* Cleans stale shard files in `/tmp/prom_multiproc` on startup.
* Exposes `render_latest()` used by `/metrics` in `ops/ops_api.py`.

Collecting metrics? Hit:

* `http://hmm_ops:8002/metrics` inside the compose network.
* `http://localhost:8002/metrics` from the host.

Engine services expose a standard `/metrics` endpoint defined in `engine/metrics.py`. All default metric names used in dashboards:

* **Counters:** `orders_submitted_total`, `orders_rejected_total`, `breaker_rejections_total`, `submit_to_ack_ms_bucket` (histogram family)
* **Gauges:** `pnl_realized_total`, `pnl_unrealized_total`, `exposure_usd`, `portfolio_equity_usd`, `ops_exposure_last_refresh_epoch`, `ops_portfolio_last_refresh_epoch`

### Observability bundle

Located in `ops/observability/`:

* `docker-compose.observability.yml` – Prometheus + Grafana services bound to the project network.
* `prometheus/prometheus.yml` – Scrape jobs for Ops API, engines, and ML service.
* `grafana/provisioning/datasources/datasource.yml` – Auto-adds Prometheus datasource.
* `grafana/provisioning/dashboards/dashboards.yml` – Loads dashboards from `/var/lib/grafana/dashboards`.
* `grafana/dashboards/hmm_trading_overview.json` – “HMM • Trading Overview” starter board focusing on equity, PnL, order flow, latency, and breaker activity.

Start the bundle only after the core stack is up so the Prometheus scrapes succeed immediately.

---

## Configuration Cheat Sheet

Most runtime knobs are environment variables defined in `.env`:

* Global trading knobs: `TRADING_ENABLED`, `TRADE_SYMBOLS`, notional limits.
* Venue-specific settings: `BINANCE_MODE`, `BINANCE_API_KEY`, `IBKR_HOST`, etc.
* OPS API: `OPS_PORT`, `OPS_WORKERS`, `OPS_API_TOKEN`.
* Metrics: `PROMETHEUS_MULTIPROC_DIR` (defaults to `/tmp/prom_multiproc` inside the container).

Engine-by-venue overrides live in `ops/env.binance`, `ops/env.bybit`, etc., and are merged on top of `.env` in `docker-compose.yml`.

---

## Key File Map

| File/Dir | Purpose |
|----------|---------|
| `engine/app.py` | FastAPI entrypoint for venue engines. Initializes risk rails, strategy hooks, and Prometheus router. |
| `engine/metrics.py` | Defines shared counters/gauges/histograms for engines. |
| `ops/ops_api.py` | Main control-plane API. Mounts strategy routes, aggregates metrics, serves `/metrics`. |
| `ops/prometheus.py` | Shared registry helper for multi-worker Prometheus exports. |
| `ops/pnl_collector.py`, `ops/exposure_collector.py`, `ops/portfolio_collector.py` | Background collectors that publish aggregated metrics into the shared registry. |
| `ops/strategy_tracker.py` | Calculates rolling Sharpe/drawdown metrics and updates `ops/strategy_registry.json`. |
| `strategies/hmm_policy/*` | Feature engineering, guardrails, policy head for HMM strategy. |
| `ml_service/app.py` | Ancillary ML API for hierarchical HMM training/inference. |
| `ops/observability/*` | Drop-in Prometheus/Grafana configuration described above. |
| `docs/OPS_RUNBOOK.md` | Operational procedures and recovery playbooks. |
| `docs/DEV_GUIDE.md` | Development workflow, testing strategy, coding standards. |

---

## Typical Control Flows

1. **Trade execution**  
   Signal arrives → `ops/strategy_router.py` → venue order via `engine/core/order_router.py` → metrics logged via `engine/metrics.py`.

2. **Governance**  
   Live metrics feed into `ops/strategy_tracker.py` → registry persisted to `ops/strategy_registry.json` → governance daemons (`ops/governance_daemon.py`, `ops/capital_allocator.py`) react based on YAML policies.

3. **Observability**  
   OPS collectors push to shared registry → Prometheus scrapes `/metrics` → Grafana dashboards visualize real-time equity/PnL/orders/latency.

4. **Model lifecycle**  
   Canary/promotion scripts (`scripts/auto_promote_if_better.py`, `ops/m16_reinforce.py`) rely on aggregated metrics and governance endpoints to roll strategies forward safely.

---

## Next Steps

* Read `docs/OPS_RUNBOOK.md` for day-to-day operational procedures.
* Consult `docs/DEV_GUIDE.md` for development workflow and instrumentation patterns.
* For a deeper architectural explanation, open `docs/SYSTEM_DESIGN.md`.

Happy shipping—and keep an eye on Grafana to watch the HMM brain work in real time.
