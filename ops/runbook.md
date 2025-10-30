# ops/runbook.md

This runbook is tailored for **Binance Spot Testnet** on macOS (Apple Silicon) with Python 3.13.

## 1) Create venv & install
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -e .

## 2) Configure environment
cp ops/env.example .env
# Fill BINANCE_API_KEY / BINANCE_API_SECRET with Spot Testnet keys.

## 3) Start the ML service
uvicorn ml_service.app:app --host 0.0.0.0 --port 8010 --workers=1

## 4) Backtest
python scripts/backtest_hmm.py --csv data/BTCUSDT_1m.csv --model engine/models/hmm_policy.pkl --symbol BTCUSDT --quote 100 --out reports/backtest_BTCUSDT.json

## 5) Start engine in paper mode (Binance Spot Testnet)
TRADING_ENABLED=false BINANCE_IS_TESTNET=true uvicorn engine.app:app --host 0.0.0.0 --port 8003 --log-level info

## 6) Promote to live trading (tiny size)
TRADING_ENABLED=true BINANCE_IS_TESTNET=false uvicorn engine.app:app --host 0.0.0.0 --port 8003 --log-level info
