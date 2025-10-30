#!/usr/bin/env bash
set -euo pipefail

DURATION="${1:-900}"   # default 15 minutes
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

# venv & deps
if [ ! -d "../.venv" ]; then
  python3 -m venv ../.venv
fi
source ../.venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -U numpy pandas matplotlib

# ensure testnet mode unless explicitly overridden
export BINANCE_IS_TESTNET="${BINANCE_IS_TESTNET:-true}"
export TRADING_ENABLED="${TRADING_ENABLED:-false}"

# 1) Run paper trading for DURATION seconds (BTC + ETH)
# Prefer 'timeout' if available; otherwise instruct manual stop.
CMD=(uvicorn engine.app:app --host 0.0.0.0 --port 8003 --log-level info)
if command -v timeout >/dev/null 2>&1; then
  timeout "${DURATION}"s "${CMD[@]}" || true
else
  echo "No 'timeout' found. Starting paper mode—press Ctrl+C to stop when you have enough data."
  "${CMD[@]}"
fi

# 2) Verify log
if [ ! -f "data/processed/feedback_log.csv" ]; then
  echo "WARNING: data/processed/feedback_log.csv not found after paper run; ensure downstream consumers have data." >&2
fi

# 3) Run calibration
python ops/calibrate_policy.py

echo "Calibration outputs:"
ls -lh data/processed/calibration/*.png || true
