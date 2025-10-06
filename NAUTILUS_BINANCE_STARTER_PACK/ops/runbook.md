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
python backtests/run_backtest.py --config backtests/configs/crypto_spot.yaml

## 5) Paper trade (testnet)
python ops/run_paper.py --symbol ${SYMBOL}

## 6) Go live tiny size (when ready)
BINANCE_IS_TESTNET=false python ops/run_live.py --symbol ${SYMBOL}
