# Nautilus HMM Starter Pack

## TL;DR
- Multi‑venue execution engine (`engine/app.py`) with Binance/Kraken adapters, in‑memory portfolio, persistence, reconciliation, and real‑time tick routing into the MA/HMM ensemble
- Risk rails and breakers (exposure caps, equity floor/drawdown, venue error‑rate) with rich metrics
- Event-driven modules: Event Breakout (dry-run first), Stop Validator (server-side SL fixups), Guards (Depeg, Funding)
- Adaptive trend stack: SMA/RSI/ATR module with auto-tuning (`TREND_AUTO_TUNE_*`) and optional symbol scanner that keeps the shortlist fresh
- Observability: Prometheus/Grafana dashboards, Telegram digest/alerts, BUS-driven events (e.g., `trade.fill`, `health.state`)
- Feature‑gated flags so you can dark‑launch each module safely

## Service Topology

| Service | Container | Host Ports | Definition | Notes |
|---------|-----------|------------|------------|-------|
| Binance trader engine | `hmm_engine_binance` | `8003` | `engine/app.py` | Live trading API; honors `TRADING_ENABLED`, risk rails, and optional scheduler. |
| Binance exporter | `hmm_engine_binance_exporter` | `9103` | `engine/app.py` | Read-only replica that streams metrics without order flow. |
| Kraken trader engine | `hmm_engine_kraken` | `8006` | `engine/app.py` | Futures execution via `engine/core/kraken.py`; uses USD quote currency. |
| Kraken exporter | `hmm_engine_kraken_exporter` | `9105` | `engine/app.py` | Mirrors Kraken portfolio state for safe scraping. |
| IBKR engine (optional) | `hmm_engine_ibkr` | `8005` | `engine/app.py` + `engine/connectors/ibkr_client.py` | Requires TWS / IB Gateway connectivity; converts quote → quantity internally. |
| Bybit stub | `hmm_engine_bybit` | `8004`, `9104` | `engine/app.py` | Uses generic engine plumbing; venue-specific adapter still TODO. |
| Ops API & dashboards | `hmm_ops` | `8002`, `9102` | `ops/ops_api.py` | Aggregates engine metrics, strategy routing, capital governance endpoints, SSE/WebSocket feeds. |
| Universe service | `hmm_universe` | `8009` | `universe/service.py` | Maintains tradable symbol set and exposes Prometheus gauges. |
| Situations service | `hmm_situations` | `8011` | `situations/service.py` | Pattern matcher with feedback loop, exposes `/metrics`. |
| Screener service | `hmm_screener` | `8010` | `screener/service.py` | Computes alpha features, posts hits to situations. |
| Executor daemon | `hmm_executor` | `9102` (metrics) | `ops/main.py` | Storm-proof probing loop that can drive orders via engine API. |
| ML service (manual) | - | `8010` (default) | `ml_service/app.py` | Run with `uvicorn ml_service.app:app --host 0.0.0.0 --port 8010` when model training endpoints are needed. |
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

Enable the built‑in MA+HMM scheduler by setting `STRATEGY_ENABLED=true` (and flip `STRATEGY_DRY_RUN=false` once comfortable). To exercise the Kraken venue, populate `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`, and set `KRAKEN_MODE=testnet|live`. IBKR connectivity requires `ib_insync` and a reachable TWS/Gateway; see `engine/connectors/ibkr_client.py`.

See docs/FEATURE_FLAGS.md for the one‑page index of important environment flags.

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
| `engine/core/` | Venue adapters (`binance.py`, `kraken.py`, `ibkr_client.py`), portfolio accounting, strategy scheduler, alert daemon. |
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
- Strategy telemetry: `strategy_ticks_total`, `strategy_tick_to_order_latency_ms`, `strategy_cooldown_window_seconds`
- Risk & health: `venue_exposure_usd`, `risk_equity_buffer_usd`, `risk_equity_drawdown_pct`, `risk_depeg_active`, `health_state`
- Event Breakout KPIs: `event_bo_*` (plans/trades/skips/trail). Dashboards:
  - `ops/observability/grafana/dashboards/event_breakout_kpis.json`
  - `ops/observability/grafana/dashboards/slippage_heatmap.json`
- `Makefile` carries helper targets (`make validate-obs`, `make smoke-prom`) to confirm scrape status and rule correctness.

See docs/OBSERVABILITY.md for quick queries and panel descriptions.

Quick queries:

```bash
curl -sG --data-urlencode 'query=rate(strategy_ticks_total{venue="binance"}[1m])' http://localhost:9090/api/v1/query | jq
curl -sG --data-urlencode 'query=histogram_quantile(0.95, rate(strategy_tick_to_order_latency_ms_bucket[5m]))' http://localhost:9090/api/v1/query | jq
```

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
