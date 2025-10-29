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

# 1) Optional lightweight backtest to refresh metrics
if [[ -n "${CALIBRATE_CSV:-}" && -f "$CALIBRATE_CSV" ]]; then
  python scripts/backtest_hmm.py --csv "$CALIBRATE_CSV" --model "${CALIBRATE_MODEL:-engine/models/hmm_policy.pkl}" --symbol "${CALIBRATE_SYMBOL:-BTCUSDT}" --quote "${CALIBRATE_QUOTE:-100}" --out "${CALIBRATE_OUT:-reports/calibration_backtest.json}"
else
  echo "(skip) CALIBRATE_CSV not set - supply CSV to refresh feedback before calibration."
fi

# 2) Warn if legacy feedback log absent
if [ ! -f "data/processed/feedback_log.csv" ]; then
  echo "WARNING: data/processed/feedback_log.csv not found; ensure calibration inputs are prepared." >&2
fi

# 3) Run calibration
python ops/calibrate_policy.py

echo "Calibration outputs:"
ls -lh data/processed/calibration/*.png || true
