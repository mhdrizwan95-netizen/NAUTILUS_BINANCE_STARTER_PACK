#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# venv
if [ ! -d "../.venv" ]; then python3 -m venv ../.venv; fi
source ../.venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -U numpy pandas scikit-learn prometheus-client matplotlib joblib

# 1) Reinforcement update (requires feedback_log.csv)
python ops/m16_reinforce.py

# 2) Canary: short backtest against baseline config
python ops/canary_sim.py --tag policy_vNext --config backtests/configs/crypto_spot.yaml

# 3) Evaluate KPI file (assume canary writes data/processed/canary_kpis.json)
KPI_JSON="data/processed/canary_kpis.json"
PASS=0
if [ -f "$KPI_JSON" ]; then
  # Example thresholds; tune as desired
  PNL=$(python - <<'PY'
import json; print(json.load(open("data/processed/canary_kpis.json")).get("pnl_total_usd", -9e9))
PY
)
  WIN=$(python - <<'PY'
import json; print(json.load(open("data/processed/canary_kpis.json")).get("winrate", 0))
PY
)
  # Conditions: non-negative pnl and winrate >= 0.48
  if python - <<PY
pnl=float("$PNL"); win=float("$WIN")
import sys; sys.exit(0 if (pnl >= -1.0 and win >= 0.48) else 1)
PY
  then PASS=1; fi
fi

# 4) Promote or abort
if [ "$PASS" -eq 1 ]; then
  echo "[M16] Canary passed. Promoting policy_vNext..."
  curl -s -X POST http://127.0.0.1:8010/promote -H "Content-Type: application/json" -d '{"tag":"policy_vNext"}' || true
else
  echo "[M16] Canary failed. Skipping promotion."
  exit 3
fi

echo "[M16] Done."
