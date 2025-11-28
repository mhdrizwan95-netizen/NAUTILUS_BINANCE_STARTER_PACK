# Nautilus HMM Starter Pack

## Quickstart

| Step | Command | Purpose |
|------|---------|---------|
| 0 | `cp env.example .env && $EDITOR .env` | Populate credentials (especially `OPS_API_TOKEN` or `OPS_API_TOKEN_FILE`) before any FastAPI service imports. |
| 0.5 | `cp env.example .env.dryrun && sed -i '' 's/OPS_API_TOKEN=.*/OPS_API_TOKEN=dry-run-token/' .env.dryrun` | Optional sanitized `.env` that `scripts/dry_run.sh` can use without leaking real secrets. |
| 1 | `make bootstrap` | Sync pinned Python/Node dependencies (hash-locked) and install pre-commit hooks. |
| 2 | `make lint typecheck test` | Run ruff, black, mypy, pytest, and frontend Vitest in one go. |
| 3 | `make audit` | Execute the read-only security + quality suite (ruff, mypy, pip-audit, npm audit, docker compose config). |
| 4 | `bash ops/repo_sync_audit.sh` | Generate FE↔BE drift, config, and control-plane reports under `audit/reports/`. |
| 5 | `make dry-run` | Launch a guarded stack (`DRY_RUN=1`) and run health checks without touching venues. |
| 6 | `make up-core` | Optional: bring the trading stack up after validating the dry run. |

> 🔐 Always export `OPS_API_TOKEN` (or point `OPS_API_TOKEN_FILE` at a secret) before running `pytest`, `make` targets, or the FastAPI apps—token loading is now deferred until first use to keep imports cheap, but requests still enforce it. For local smoke tests you can reuse the default `test-ops-token-1234567890`.

Refer to `docs/secrets.md` for the full secrets policy and recommended ways to keep `.env` data out of git.

### Deterministic audits & dry runs

- Audit stages honor throttles: `MAKEFLAGS="-j1" SKIP_DOCKER=1 SKIP_FRONTEND=1 SKIP_TESTS=1 make audit` keeps the run CPU-light and skips docker/Node work when you only need Python lint+type coverage. Re-enable phases incrementally by clearing the corresponding env vars.
- `scripts/audit.sh` and `make bootstrap` run `npm ci --ignore-scripts --prefer-offline` so installs are reproducible and side-effect free; drop those flags only if a dependency truly requires lifecycle scripts.
- `scripts/dry_run.sh` is the underlying launcher behind `make dry-run`. It stages compose services with `docker compose up --no-start`, exports `DRY_RUN=1`, and runs `/health` probes before tailing; pass `DRY_RUN_DETACH=1` to exit after health checks.
- `pre-commit` includes `detect-secrets`—refresh `.secrets.baseline` whenever you rename env vars or move secrets so CI and local hooks stay in sync.

Try `make help` for the legacy targets while the new lifecycle gets folded into the rest of the Makefile.

## Stack Highlights
- Python 3.11 FastAPI services (`engine`, `ops`, `services/*`) backed by `nautilus_trader`, risk rails, and governance daemons.
- React 18 + Vite Command Center with TanStack Query, Radix UI, Vitest, and Playwright for E2E.
- Docker Compose orchestration for trading, ML retraining, and observability bundles.
- `scripts/audit.sh` (read-only checks) and `scripts/dry_run.sh` (safe launch) keep local workflows deterministic.

## Service Topology

| Service | Container | Host Ports | Definition | Notes |
|---------|-----------|------------|------------|-------|
| Binance trader engine | `hmm_engine_binance` | `8003` | `engine/app.py` | Live trading API; honors `TRADING_ENABLED`, risk rails, and optional scheduler. |
| Binance exporter | `hmm_engine_binance_exporter` | `9103` | `engine/app.py` | Read-only replica that streams metrics without order flow. |
| Ops API & dashboards | `hmm_ops` | `8002`, `9102` | `ops/ops_api.py` | Aggregates engine metrics, strategy routing, capital governance endpoints, SSE/WebSocket feeds. |
| Universe service | `hmm_universe` | `8009` | `universe/service.py` | Maintains tradable symbol set and exposes Prometheus gauges. |
| Situations service | `hmm_situations` | `8011` | `situations/service.py` | Pattern matcher with feedback loop, exposes `/metrics`. |
| Screener service | `hmm_screener` | `8010` | `screener/service.py` | Computes alpha features, posts hits to situations. |
| Executor daemon | `hmm_executor` | `9102` (metrics) | `ops/main.py` | Storm-proof probing loop that can drive orders via engine API. |
| ML service API | `hmm_ml_service` | `8015` | `services/ml_service/app/main.py` | Brought in via `compose.autotrain.yml`; hosts `/train`, `/predict`, and model registry endpoints. |
| ML scheduler | `hmm_ml_scheduler` | - | `services/ml_service/app/scheduler.py` | Cron worker that claims ledger files and triggers retrains; shares volumes with the API. |
| Param controller | `hmm_param_controller` | `8016` | `services/param_controller/app/main.py` | Bandit-driven preset selection for strategies; mounts shared SQLite state. |
| Data ingester | `hmm_data_ingester` | `8013` | `services/data_ingester/app/main.py` | CCXT-powered fetcher that writes OHLCV chunks to `/data/incoming` and registers them in the ledger. |
| Data backfill job | `hmm_data_backfill` | - | `services/data_ingester/app/backfill.py` | One-shot historical loader; reuses ledger + watermarks to avoid overlap with live ingestion. |
| Backtest runner | `hmm_backtest_runner` | - | `services/backtest_suite/app/cli.py` | Prequential simulator that replays research data, retrains on cadence, and writes results under `/results`. |
| Observability bundle | `hmm_prometheus`, `hmm_grafana`, `hmm_loki`, `hmm_promtail` | `9090`, `3000`, `3100` | `ops/observability/docker-compose.observability.yml` | Scrape engine/ops metrics, ship logs, and auto-provision dashboards. |

## Runtime Flow

```
Strategy scheduler / external ML ─┐
                                 ▼
                         RiskRails.check_order
                                 ▼
OrderRouterExt → venue client → exchange
                                 ▼
Portfolio.apply_fill → SnapshotStore → SQLite log
                                 ▼
Prometheus metrics → Ops API dashboards → Grafana/alerts
```

Universe, situations, and screener services produce symbol lists and pattern hits that the strategy loop or executor can consume. `engine/core/event_bus.py` coordinates async notifications across subsystems.

### Unified data flow

```mermaid
flowchart LR
    subgraph Market Data
        WS[WebSocket / REST feeds]
    end
    subgraph Engine
        BUS(EventBus)
        Ticks[market.tick]
        Sys[Systematic Strategies\n(HMM, Trend, Scalp, Momentum)]
        Events[Event-driven Strategies\n(Listing Sniper, Meme Sentiment, Airdrop)]
        Risk[RiskRails]
        Router[OrderRouter]
        Port[Portfolio + Persistence]
    end
    subgraph External Signals
        External[External services\n(universe, screener, webhooks)]
    end

    WS -->|tick events| Ticks
    Ticks --> Sys
    External -->|POST /events/external| BUS
    BUS --> Events
    Sys --> Risk
    Events --> Risk
    Risk --> Router --> Exchange[(Venue)] -->|fills| Port
    Port --> Grafana[(Prometheus/Grafana)]
```

Tick data drives the systematic stack, while external services publish structured payloads to `events.external_feed`. Every strategy funnels through `RiskRails` before orders leave the engine.

## Getting Started

```bash
# 1) Copy environment template and review credentials/risk knobs.
cp env.example .env

# 2) Ensure the shared Docker network exists (compose expects it).
docker network create nautilus_trading_network || true

# 3) Build images and start the core trading stack.
make build
make up-core

# 4) (Optional) Launch observability.
make up-obs

# 5) Verify exporter metrics and accounting invariants.
make smoke-exporter

# 6) Stop services when finished.
make down
make down-all  # also stops Prometheus/Grafana
```

### Autotrain overlay

Run the ingestion → training → parameter loop alongside the core engine with the
compose overlays shipped in this repo:

```bash
# ML + parameter loop
docker compose -f docker-compose.yml -f compose.autotrain.yml up -d --build data_ingester ml_service ml_scheduler param_controller

# Historical replay (prequential simulator)
docker compose -f docker-compose.yml -f compose.autotrain.yml -f compose.backtest.yml up -d --build backtest_runner

# One-shot Binance backfill
docker compose -f docker-compose.yml -f compose.autotrain.yml -f compose.backfill.yml run --rm data_backfill
```

The services share the `/data`, `/models`, and `/shared` volumes declared in the overlays,
so ledger state, model registries, and backtest artifacts stay consistent between runs.

Enable the built‑in MA+HMM scheduler by setting `STRATEGY_ENABLED=true` (and flip `STRATEGY_DRY_RUN=false` once comfortable). Populate the Binance API credentials (`BINANCE_API_KEY`, `BINANCE_API_SECRET`) or demo keys before taking the guard rails off; Binance is now the only supported venue.

See docs/FEATURE_FLAGS.md for the one‑page index of important environment flags.

## Command Center UI

The React/TypeScript Command Center ships inside the `ops` service image. Any target that brings the core stack online (`make up-core`, `make autopilot`, etc.) now bakes and serves the SPA directly from the Ops API container. Once `ops` is healthy, open [http://localhost:8002/](http://localhost:8002/) to reach the UI; all API calls are routed to the co-located `/api/*` endpoints inside the same container, so no extra proxy or compose services are required.

> Legacy “Deck” assets have been removed; the Ops API no longer serves `dashboard/static/*`. If you still need a kiosk view, fork the React Command Center or consume the Ops REST endpoints directly.

### Configuration overview

The `.env.example` file is now generated from `engine/config/defaults.py`, so every knob surfaced in the codebase appears in a single, well-documented template. Regenerate it with:

```bash
python scripts/generate_env_example.py
```

Key tips:

* `TRADE_SYMBOLS` is the global allowlist. Leave it as `*` to permit every discovered symbol, or provide a comma-separated list (e.g., `BTCUSDT,ETHUSDT`).
* Each strategy (`TREND_*`, `SCALP_*`, `MOMENTUM_RT_*`, `MEME_SENTIMENT_*`) has its own section with defaults that match the loader logic. Setting a per-strategy `*_SYMBOLS` value overrides `TRADE_SYMBOLS` for that module; blank or `*` falls back to the global list.
* Risk rails (`MIN_NOTIONAL_USDT`, `EXPOSURE_CAP_*`, etc.) align with the defaults enforced by `engine.config.load_risk_config()` and `RiskRails`. Lower the limits to stay in “paper-safe” territory; raise them only once you have live liquidity to support it.
* Deprecated aliases (`SOCIAL_SENTIMENT_*`) remain as commented entries so legacy deployments can copy/paste the correct replacements without guesswork.

### Backtesting

The starter pack does **not** ship a production-grade backtest harness yet. Earlier placeholders such as `run_backtest.py` were removed so nobody accidentally relies on incomplete tooling. Research utilities that still live under `scripts/` remain strictly experimental; treat them as reference material until the official harness (data adapters, fills/slippage model, deterministic replay clock, seeded randomness) lands. Progress is tracked in `ROADMAP.md`.

## Key Directories

| Path | Purpose |
|------|---------|
| `engine/` | Execution service: FastAPI app, order router, risk rails, metrics, persistence, reconciliation. |
| `engine/core/` | Binance venue adapter (`binance.py`), portfolio accounting, strategy scheduler, alert daemon. |
| `engine/strategies/` | Unified strategy implementations (MA+HMM policy, ensemble fusion, trend, scalping, momentum, listing sniper, meme sentiment, airdrop promo, symbol scanner). |
| `engine/guards/` | Depeg & Funding guards (halt/trim/hedge on adverse conditions). |
| `engine/execution/` | Per‑symbol execution overrides (auto size‑cutback & mute). |
| `engine/storage/` | SQLite facade (`sqlite.py`) and schema for orders, fills, positions, equity snapshots. |
| `ml_service/` | Optional FastAPI microservice for training/inference, model registry, hierarchical HMM tooling. |
| `ops/` | Ops API, governance daemons, capital allocator, exposure collector, alerting scripts, executor logic. |
| `ops/observability/` | Prometheus & Grafana configuration, alert rules, helper scripts (`validate_obs.sh`). |
| `engine/ops/` | Health notifier, stop validator, WS fills listener runner. |
| `universe/`, `situations/`, `screener/` | Supporting microservices for symbol universe management and alpha signal generation. |
| `scripts/` | CLI utilities for model training, backtests, soak tests, and venue diagnostics. |
| `tests/` | Pytest suite covering engine, strategy, ops, and ML components. |
| `docs/` | Living documentation: system design, developer guide, ops runbook, incident retrospectives. |

## Observability & Metrics

- Every service exposes `/metrics`; engine counters and gauges live in `engine/metrics.py`.
- **Primary command centre**: Grafana dashboard `Command Center v2` (`ops/observability/grafana/dashboards/command_center_v2.json`), auto-provisioned under folder “HMM”.
  - Panels cover health (`health_state`, `engine_component_uptime_seconds`), risk (`venue_exposure_usd`, `risk_equity_drawdown_pct`), trading (`orders_*`, `fees_paid_total`), latency (`http_request_latency_seconds`, `ws_message_gap_seconds`), strategy/situations, and ops/governance (`control_actions_total`, `idempotency_*`).
- Supporting dashboards: `command_center.json` (legacy), `venue_binance.json`, `trend_strategy_ops.json`, `event_breakout_kpis.json`, `slippage_heatmap.json`.
- Prometheus scrape/rules live under `ops/observability/prometheus/`; helper targets (`make validate-obs`, `make smoke-prom`) confirm scrape status and rule correctness.
- Optional external UIs can consume the same Ops API, but running Prometheus + Grafana is sufficient for day-to-day operations.

See docs/OBSERVABILITY.md for quick queries and panel descriptions.

Quick queries:

```bash
curl -sG --data-urlencode 'query=rate(strategy_ticks_total{venue="binance"}[1m])' http://localhost:9090/api/v1/query | jq
curl -sG --data-urlencode 'query=histogram_quantile(0.95, rate(strategy_tick_to_order_latency_ms_bucket[5m]))' http://localhost:9090/api/v1/query | jq
```

### Quick start: Grafana-only command centre

1. Export env vars (`source .env` or `.env.dryrun.live`) to configure OPS/engine credentials.
2. Launch the trading stack in dry-run or live mode (`make autopilot` or `make dry-run`).
3. Bring up Prometheus + Grafana (`make autopilot-observe`).
4. Open http://localhost:3000 → folder “HMM” → **Command Center v2**. No bespoke web UI is required; all control actions can be issued via the Ops API and observed via Grafana.

## Strategy & Modules

### Systematic stack (tick-driven)
- **MA + HMM ensemble** — `engine/strategies/policy_hmm.py`, `engine/strategies/ensemble_policy.py`. Uses `engine/models/hmm_calibration.json` (or `HMM_CALIBRATION_PATH`) for per-symbol confidence tuning.
- **Trend follower** — `engine/strategies/trend_follow.py`. Toggle with `TREND_ENABLED`; optional auto-tune knobs (`TREND_AUTO_TUNE_*`) adjust RSI/ATR windows on the fly.
- **Scalper** — `engine/strategies/scalping.py`. Controlled by `SCALP_ENABLED`; respects spread/latency guardrails and per-symbol cooldowns.
- **Momentum (real-time)** — `engine/strategies/momentum_realtime.py`. Watches fast moves using configurable volume/momentum thresholds.

### Event-driven modules (`events.external_feed`)
- **Listing Sniper** — `engine/strategies/listing_sniper.py`. Reacts to Binance listing announcements and can trade the new pair instantly. Flags: `LISTING_SNIPER_ENABLED`, `LISTING_SNIPER_DRY_RUN`, `LISTING_SNIPER_MAX_NOTIONAL_USD`, `LISTING_SNIPER_COOLDOWN_SEC`.
- **Meme Coin Sentiment** — `engine/strategies/meme_coin_sentiment.py`. Listens to social feeds (e.g., `twitter_firehose`, `dex_whale`) and sizes positions based on sentiment score. Flags: `MEME_SENTIMENT_ENABLED`, `MEME_SENTIMENT_SOURCES`, `MEME_SENTIMENT_MIN_SIGNAL`.
- **Airdrop & Promotion Watcher** — `engine/strategies/airdrop_promo.py`. Captures exchange promo events and opportunistic rebates. Flags: `AIRDROP_PROMO_ENABLED`, `AIRDROP_PROMO_SOURCES`, `AIRDROP_PROMO_MAX_NOTIONAL_USD`.
- **Symbol Scanner** — `engine/strategies/symbol_scanner.py`. Maintains a rolling shortlist of eligible symbols; controlled via `SYMBOL_SCANNER_*`.

All strategies respect the global allowlist (`TRADE_SYMBOLS`) unless a module-specific `*_SYMBOLS` override is provided. The EventBus handles fan-out; synchronous handlers run in a thread pool sized by `EVENTBUS_MAX_WORKERS` so blocking operations cannot freeze the loop.

The MA+HMM ensemble uses a shared calibration profile so backtests and live trading stay aligned. Create/adjust `engine/models/hmm_calibration.json` (or `HMM_CALIBRATION_PATH`) with per-symbol overrides:

```json
{
  "*": {"confidence_gain": 1.0, "quote_multiplier": 1.0, "cooldown_scale": 1.0},
  "BTCUSDT": {"confidence_gain": 1.15, "quote_multiplier": 0.75, "cooldown_scale": 0.8}
}
```

`policy_hmm.py` and the ensemble apply these factors live; the file reloads every ~60s.

Supporting modules (enable with flags):

- Event Breakout: `engine/strategies/event_breakout.py` (start dry‑run; trailing via `event_breakout_trail.py`).
- Protective guards: Depeg (`engine/guards/depeg_guard.py`), Funding (`engine/guards/funding_guard.py`).
- Stop Validator: `engine/ops/stop_validator.py` repairs missing SLs and can ping Telegram.
- Execution overrides: `engine/execution/venue_overrides.py` handles size cutback & mute.
- Risk‑parity sizing: `engine/risk/sizer.py` adjusts per-symbol allocations.

To profile end‑to‑end: target median `strategy_tick_to_order_latency_ms` < 100 ms; watch cooldown and order/ tick ratios to validate expected firing.

## Further Reading

 - docs/FEATURE_FLAGS.md — quick index of environment flags
 - docs/OBSERVABILITY.md — dashboards, PromQL, and SLOs
 - docs/OPS_RUNBOOK.md — daily checks, incident playbooks, staged go‑live
 - hmm_operator_handbook.md — strategy‑operator playbook and ML service notes

Keep documentation up to date when adding venues, strategies, or governance features—this README should always describe what actually runs in `docker-compose.yml`.

### Trend auto-tune + symbol scanner
- Enable the adaptive trend module with `TREND_ENABLED=true` (keep `TREND_DRY_RUN=true` until you are ready to fire orders). Flip `TREND_AUTO_TUNE_ENABLED=true` to let it log every trade to `data/runtime/trend_auto_tune.json`, monitor rolling win-rate, and gently adjust RSI windows, ATR stop/target multiples, and cooldown bars (knobs: `TREND_AUTO_TUNE_MIN_TRADES`, `..._INTERVAL`, `..._STOP_MIN/MAX`, `..._WIN_LOW/HIGH`). Logs show `[TREND-AUTO] params=...` when an adjustment happens.
- Switch on `SYMBOL_SCANNER_ENABLED=true` to let the symbol scanner periodically rank the configured universe (`SYMBOL_SCANNER_UNIVERSE`) using momentum/ATR/liquidity filters. Only the top `SYMBOL_SCANNER_TOP_N` symbols are routed into the trend module; the shortlist persists to `data/runtime/symbol_scanner_state.json` and exposes Prometheus metrics (`symbol_scanner_score`, `symbol_scanner_selected_total`).
- Leave both flags off to fall back to the global `TRADE_SYMBOLS` allowlist (or allow-all `*`).
