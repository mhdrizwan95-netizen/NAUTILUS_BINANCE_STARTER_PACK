
# Robust Autonomous Backtesting Suite

This suite **mirrors the live learning loop**: it ingests data chunk‑by‑chunk, triggers **retraining and promotion** on a schedule, hot‑reloads models, queries the **Param Controller** for dynamic strategy parameters, and simulates execution with costs. It uses the same ledger (exactly‑once file registry) as production — no double‑training of files, and optional strict **bar‑exactly‑once** mode (via ml_service).

## What’s inside

- `services/backtest_suite/` — backtest runner (Python 3.11)
  - `app/driver.py` — feeds the ledger from your **research** CSVs in incremental chunks
  - `app/engine.py` — event loop: ingest → train → param → execute → record
  - `app/strategy_*` — strategy interface + a simple **momentum_breakout** demo
  - `app/execution.py` — simple execution model with fee/slippage
  - `app/metrics.py` — performance helpers
  - `app/clock.py` — simulation clock
- `compose.backtest.yml` — adds a `backtest_runner` service that talks to `ml_service` & `param_controller`

> This suite expects the ML Service and Param Controller from the Autotrain Stack to be running (see previous bundle).

## Quick start

1. Prepare research data (CSV with **timestamp, open, high, low, close, volume**) under:
   ```
   research/BTC_USDT/1m/file1.csv
   research/BTC_USDT/1m/file2.csv
   ```

2. Launch the stack (including `ml_service`, `param_controller`, etc.) then add the backtest runner:
   ```bash
   docker compose -f docker-compose.yml -f compose.autotrain.yml -f compose.backtest.yml up -d --build
   ```

3. The `backtest_runner` will:
   - slice research CSVs into **CHUNK_ROWS** pieces and register them in the ledger,
   - trigger `/train` on **ml_service** on your cadence,
   - query **Param Controller** for parameters each bar,
   - simulate the demo **momentum_breakout** strategy,
   - write results to the **results** volume (`/results/equity.csv`, `/results/trades.csv`).

## Configuration (env)

- `RESEARCH_DIR=/research` — where your historical CSVs live
- `LEDGER_DB=/shared/manifest.sqlite` — shared ledger path
- `DATA_INCOMING=/data/incoming` — landing area (like live ingester)
- `CHUNK_ROWS` — bars per ingest tick (default 1000)
- `TRAIN_CRON_MINUTES` — retrain cadence in minutes (e.g., 360 = 6h)
- `FEE_BP`, `SLIPPAGE_BP` — execution frictions
- `MAX_STEPS` — iteration cap

## Exactly‑once & leakage

- The **driver** writes chunks into the ledger, just like live. The **trainer** operates with the same rules; if `EXACTLY_ONCE=true` in `ml_service`, bars are trained at most once. In sliding‑window mode, past bars can be reused within the window (recommended for HMM quality).
- To add a **walk‑forward promotion gate** (P&L after costs), reuse this sim to evaluate candidate models on forward windows before promotion.

## Extending strategies

Implement the interface in `strategy_base.Strategy` and add your logic in `on_bar`. Register presets in the Param Controller (or hardcode for testing). To run multiple strategies/instruments, spawn strategy instances in `engine.py` and aggregate P&L.

## Outputs

- `/results/equity.csv` — marked‑to‑market equity over time
- `/results/trades.csv` — executed actions with notional and P&L (where applicable)

## Notes

- The demo strategy is minimal for clarity. Integrate your real strategies through the same interface and have them read params from the Param Controller.
- For compute‑heavy models, insert **training latency** (sleep) in the backtest runner to emulate downtime.
- Always embargo/purge overlaps if you extend the trainer locally — or keep training in `ml_service` to guarantee the same code path as production.
