# Nautilus HMM – Project Overview

This brief is for new developers joining the Nautilus trading stack. It captures the system’s north star, current wiring and plumbing, what is already live, and the most important remaining work.

## 1. North Star

- **Mission:** Operate an autonomous Binance trading organism that can learn, evaluate, and deploy market-making or directional strategies with tight governance and observability.
- **Principles:** Safety before speed (risk rails + breakers), measurable improvement (backtests + live canaries), clear separation of duties (execution vs. control plane), and always-on telemetry (Prometheus/Grafana).
- **Target state:** A resilient Binance engine fleet that accepts model signals, enforces policy, self-monitors, and promotes better models automatically while exposing a transparent operational control surface.

## 2. Current Snapshot

| Area | Status | Notes |
|------|--------|-------|
| Execution engine | ✅ | `engine/app.py` serves REST APIs for orders, reconciliation, metrics; hardened for **Binance spot/futures only**. |
| Strategy runtime | ✅ | Built-in MA + HMM ensemble plus unified strategies (`engine/strategy.py`, `engine/strategies/policy_hmm.py`, `engine/strategies/trend_follow.py`, `engine/strategies/listing_sniper.py`). |
| ML tooling | ✅ (auto) | `ml_service/app.py` provides training/inference endpoints and model registry; auto-promotion scripts live in `scripts/`. |
| Ops control plane | ✅ | `ops/ops_api.py` aggregates metrics, exposes governance endpoints, supports WebSocket feeds, and coordinates strategy routing + capital allocation. |
| Governance | ✅ | `ops/capital_allocator.py`, `ops/strategy_router.py`, policy JSON/YAML inputs; playbooks via `ops/m20_playbook.py`, `ops/m25_governor.py`. |
| Observability | ✅ | Prometheus + Grafana + Loki bundle in `ops/observability/`, dashboards auto-provisioned (Command Center, venue views); metrics defined in `engine/metrics.py` and `ops/prometheus.py`. |
| Persistence | ✅ | Portfolio snapshots (`engine/state.py`), idempotency cache, JSONL logs, SQLite (`engine/storage/sqlite.py`). |
| Supporting services | ✅ | Universe, Situations, Screener FastAPI microservices provide symbol selection and pattern detection. |
| Documentation | ✅ | Updated README, system design, dev guide, ops runbook (`docs/`). |

## 3. System Topology

```
Strategies / ML  ─┐
                  │  (signals)
                  ▼
             RiskRails
                  ▼
           OrderRouterExt ──► Venue client (Binance)
                  ▼
            Portfolio / Persistence
                  ▼
      Prometheus metrics & Event bus
                  ▼
         Ops API / Governance layer
                  ▼
     Dashboards, alerts, external tooling
```

- **Engine services:** Trader/exporter pair for Binance (`hmm_engine_binance`, `hmm_engine_binance_exporter`), each exposing `/orders`, `/metrics`, `/readyz`.
- **Control plane:** `hmm_ops` orchestrates governance, capital allocation, and telemetry aggregation; executor (`hmm_executor`) can drive live trades via engine API.
- **Supporting apps:** `hmm_universe`, `hmm_situations`, `hmm_screener` share symbol intelligence and feed the strategy layer.
- **Observability:** Prometheus (`hmm_prometheus`), Grafana (`hmm_grafana`), Loki/Promtail for logs; dashboards assignable by venue/model.

## 4. Data & Control Flow

1. **Signal generation:** Engine scheduler, external ML service, or executor produces a strategy signal.
2. **Risk gating:** `RiskRails.check_order` enforces trading toggle, notional bounds, symbol allowlist, exposure caps, rate limits, breakers.
3. **Routing:** `OrderRouterExt` normalises symbols, applies venue specs (min qty/notional), and submits via the Binance client (`BinanceREST`).
4. **Persistence:** Fills update the in-memory `Portfolio`, flush to snapshots (`engine/state.py`), append JSONL audit logs, and enqueue SQLite writes for orders/fills (`engine/storage/sqlite.py`).
5. **Telemetry:** `engine/metrics.py` updates counters/gauges/histograms; exporters expose `/metrics` for Prometheus scraping.
6. **Ops aggregation:** The Ops API merges metrics, updates dashboards, enforces governance policies, and emits events via SSE/WebSockets.
7. **Governance loop:** Capital allocator, canary manager, and guardian playbooks adjust weights, allocations, and kill switches based on live data and policy definitions.

## 5. Risk, Governance, and Safety Nets

- **Risk rails:** Configurable via environment variables (`MIN_NOTIONAL_USDT`, `MAX_ORDERS_PER_MIN`, `TRADE_SYMBOLS`) and `engine/policies.yaml`.
- **Circuit breakers:** `venue_error_rate_pct`, `breaker_state`, and `breaker_rejections_total` guard against venue instability.
- **Capital governance:** `ops/capital_policy.json`, `ops/capital_allocations.json`, and strategy weights JSON feed the allocator/router.
- **Playbooks:** `ops/m20_playbook.py` (guardian), `ops/m25_governor.py` (compliance) provide scripted mitigation actions.
- **Recovery:** `engine/reconcile.py` plus `engine/core/reconcile_daemon.py` reconcile missed fills on startup or manual trigger.

## 6. Observability & Tooling

- **Metrics:** Engine gauges (cash/equity/exposure, mark prices, submit-to-ack latency), exporter heartbeats, Ops agg metrics (`ops/prometheus.py`).
- **Dashboards:** Command Center, venue-specific views, and model telemetry derived from Prometheus jobs.
- **Alerts:** Prometheus rules under `ops/observability/prometheus/rules/*.yml` (trading, alerts) feed Grafana/alertmanager (hook up to chat/incident channels as needed).
- **Validation:** `ops/observability/validate_obs.sh` ensures dashboards and queries stay green.

## 7. Achievements vs. Remaining Work

### Delivered
- Binance trading engine with trader/exporter roles and persistence.
- Strategy scheduler with MA + HMM ensemble, bracket management, and ensemble fusion.
- Manual ML service with hierarchical HMM tooling and promotion scripts.
- Ops control plane with governance APIs, capital allocation, strategy routing, executor support.
- Observability stack with metrics, dashboards, log ingestion, and validation tooling.
- Documentation refresh (README, system design, developer guide, ops runbook, incident write-ups).
- Risk management (exposure caps, breakers, rate limits) and automated reconciliation.

### In Progress / Next Priorities
- **ML service integration:** Optionally containerise and wire into `docker-compose.yml` with RBAC and hot reload.
- **Automation:** Expand guardian/governor automation, integrate notifications (Slack/Telegram) via `ops/m22_notify.py`.
- **Testing:** Strengthen end-to-end tests (multi-venue integration, strategy scheduler) and add coverage for new connectors.
- **Secrets & compliance:** Harden secret management (avoid plain `.env` at scale), document approval workflows.
- **Scalability:** Plan horizontal scaling (multiple engine instances per venue) and multi-region observability (Prometheus federation).

## 8. Suggested Onboarding Path

1. **Read** `README.md`, this overview, `docs/SYSTEM_DESIGN.md`, and `docs/OPS_RUNBOOK.md`.
2. **Bootstrap** local stack (`make build`, `make up-core`, `make up-obs`); confirm metrics via `make smoke-exporter`.
3. **Inspect** strategy loop (`engine/strategy.py`) and risk rails (`engine/risk.py`) to understand order eligibility.
4. **Explore** Ops API (`ops/ops_api.py`, `/status`, `/kill`, `/strategy/*`) and dashboards (Grafana Command Center).
5. **Review** governance configs (`ops/strategy_weights.json`, `ops/capital_policy.json`, `engine/policies.yaml`) and adjust in a sandbox.
6. **Walk through** ML workflow (`scripts/train_hmm_policy.py`, `scripts/auto_promote_if_better.py`, `ml_service/app.py`) to see how new models ship.
7. **Plan next work**: pick an outstanding item above (e.g., ML service automation) and coordinate with the team.

With these references, a new developer should understand how the system is wired today, what has been accomplished, and the north-star direction for future iterations.
