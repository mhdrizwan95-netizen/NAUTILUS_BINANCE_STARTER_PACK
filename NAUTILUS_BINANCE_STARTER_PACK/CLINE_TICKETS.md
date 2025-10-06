# Cline Milestone Board — Nautilus HMM on Binance (Spot)
# Branch: feat/binance-hmm-v1

## M0 — Bootstrap
- Create venv, install deps (pyproject provided).

## M1 — Binance adapters (paper)
- Fill ops/run_paper.py to instantiate Binance Spot testnet data+exec clients and run engine.

## M2 — Features
- Implement compute_features() and rolling standardization. Add deque windows and per-session stats.

## M3 — ML service
- Implement real HMM + Policy; add /train and /partial_fit; persist to ml_service/model_store.

## M4 — Strategy
- Convert strategy.py to real Nautilus Strategy subclass; wire order placement and cache lookups. Add backtests/run_backtest.py using BacktestEngine.

## M5 — Guardrails & VWAP
- Enforce gates and implement VWAP anchoring & dynamic spread tolerance. Log reason codes.

## M7 — Paper demo
- 60 min unattended run; export CSV: trades, state timeline, guardrails.

## M8 — Live tiny
- Flip to live (BINANCE_IS_TESTNET=false); qty tiny; daily parquet rollups.
