#!/usr/bin/env bash
set -euo pipefail

DURATION="${1:-900}"   # default 15 minutes
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# venv & deps
if [ ! -d "../.venv" ]; then
  python3 -m venv ../.venv
fi
source ../.venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -U numpy pandas matplotlib

# ensure testnet mode unless explicitly overridden
export BINANCE_IS_TESTNET="${BINANCE_IS_TESTNET:-true}"
export TRADING_ENABLED="${TRADING_ENABLED:-true}"

# 1) Run paper trading for DURATION seconds (BTC + ETH)
# Prefer 'timeout' if available; otherwise instruct manual stop.
if command -v timeout >/dev/null 2>&1; then
  timeout "${DURATION}"s python ops/run_paper.py --symbol BTCUSDT.BINANCE --symbol ETHUSDT.BINANCE || true
else
  echo "No 'timeout' found. Starting paper mode—press Ctrl+C to stop when you have enough data."
  python ops/run_paper.py --symbol BTCUSDT.BINANCE --symbol ETHUSDT.BINANCE
fi

# 2) Verify log
if [ ! -f "data/processed/feedback_log.csv" ]; then
  echo "ERROR: feedback_log.csv not found after paper run." >&2
  exit 1
fi

# 3) Run calibration
python ops/calibrate_policy.py

echo "Calibration outputs:"
ls -lh data/processed/calibration/*.png || true
