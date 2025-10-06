#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"
export PYTHONPATH="$ROOT"
if [ ! -d "../.venv" ]; then
  python3 -m venv ../.venv
fi
source ../.venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -U numpy pandas matplotlib pyyaml

# 1) Run backtest to produce feedback_log.csv (short run config)
python backtests/run_backtest.py --config backtests/configs/crypto_spot.yaml

# 2) Verify log
if [ ! -f "data/processed/feedback_log.csv" ]; then
  echo "ERROR: feedback_log.csv not found after backtest." >&2
  exit 1
fi

# 3) Run calibration
python ops/calibrate_policy.py

echo "Calibration outputs:"
ls -lh data/processed/calibration/*.png || true
