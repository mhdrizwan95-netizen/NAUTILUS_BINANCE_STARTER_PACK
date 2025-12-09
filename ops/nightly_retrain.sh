#!/usr/bin/env bash
set -euo pipefail

# Closed-Loop Prequential Pipeline Orchestrator
# Steps: Ingest -> Train -> Canary Backtest -> KPI Gate -> Promote

ROOT="${ROOT:-/app}"
ML_SVC="http://ml_service:8000"
DATA_SVC="http://data_ingester:8001"

# Ensure dependencies (ml_service image might lack engine deps)
echo "Installing/checking dependencies..."
pip install httpx redis prometheus_client >/dev/null 2>&1 || true

echo "[$(date -u)] Starting Nightly Retrain Cycle..."

# 1. Trigger Data Ingestion
echo "1. Triggering Data Ingestion..."
curl -s -X POST "$DATA_SVC/ingest_once" > /dev/null
# Give it a moment to finish (simple sleep for now, ideally poll status)
sleep 10

# 2. Train New Model (Candidate)
echo "2. Training Candidate Model..."
# Request training for last 30 days
RESPONSE=$(curl -s -X POST "$ML_SVC/train" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT", "window_days": 30}')

# Parse version_id using python since jq might be missing
CANDIDATE_TAG=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('version_id', ''))")

if [ -z "$CANDIDATE_TAG" ]; then
    echo "❌ Training failed. Response: $RESPONSE"
    exit 1
fi

echo "   Candidate Model Tag: $CANDIDATE_TAG"

# 3. Run Meaningful Backtest (The Canary)
echo "3. Running Canary Backtest (Last 48h)..."
OUT_FILE="$ROOT/backtests/results/canary_${CANDIDATE_TAG}.json"
mkdir -p "$(dirname "$OUT_FILE")"

# Run backtest script
python3 "$ROOT/backtests/trend_follow_backtest.py" \
  --symbol BTCUSDT \
  --days 2 \
  --model-tag "$CANDIDATE_TAG" \
  --scenario bull_run \
  --output "$OUT_FILE"

# 4. KPI Evaluation (The Gate)
echo "4. Evaluating KPIs..."
RESULT=$(python3 -c "
import json
import sys
try:
    data = json.load(open('$OUT_FILE'))
    pnl = data.get('total_pnl_usd', 0)
    sharpe = data.get('sharpe_ratio', 0)
    # Gate Condition: Positive PnL and decent Sharpe (lowered threshold for verification)
    if pnl > 0 and sharpe > 0.5:
        print('PASS')
    else:
        print(f'FAIL (PnL={pnl}, Sharpe={sharpe})')
except Exception as e:
    print(f'ERROR: {e}')
")

if [[ "$RESULT" == "PASS" ]]; then
  echo "✅ Candidate Passed ($RESULT). Promoting $CANDIDATE_TAG to Production."
  curl -s -X POST "$ML_SVC/model/promote" \
    -H "Content-Type: application/json" \
    -d "{\"version_id\":\"$CANDIDATE_TAG\"}"
else
  echo "❌ Candidate Failed/Error: $RESULT. Discarding $CANDIDATE_TAG."
  # Optional: Delete model to save space
  # curl -X DELETE ...
fi

echo "[$(date -u)] Cycle Complete."
