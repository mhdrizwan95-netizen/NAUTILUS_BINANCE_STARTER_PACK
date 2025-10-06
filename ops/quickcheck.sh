#!/usr/bin/env bash
set -euo pipefail
BASE="http://127.0.0.1"
ML="$BASE:8010"; OPS="$BASE:8060"; DASH="$BASE:8050"

echo "== ML HEALTH =="
curl -s "$ML/health" && echo

echo "== TRAIN =="
TAG=$(curl -s -X POST "$ML/train" -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT","feature_sequences":[[[1,2,3],[2,3,4],[3,4,5]]]} ' | python - <<'PY'
import sys,json;print(json.load(sys.stdin).get("tag",""))
PY)
echo "TAG=$TAG"

echo "== MODELS =="
curl -s "$ML/models" && echo

echo "== BACKTEST =="
python backtests/run_backtest.py --config backtests/configs/crypto_spot.yaml || true
ls -lh data/processed/{trades.csv,state_timeline.csv,guardrails.csv,data_quality_issues.csv} || true

echo "== DASH METRICS SNAPSHOT =="
curl -s "$DASH/metrics" | head -n 20

echo "== OPS STATUS =="
curl -s "$OPS/status" && echo

echo "== CANARY & PROMOTE =="
python ops/canary_sim.py --tag "$TAG" --config backtests/configs/crypto_spot.yaml || true
curl -s -X POST "$ML/promote" -H "Content-Type: application/json" -d "{\"tag\":\"$TAG\"}" && echo
curl -s "$ML/models" && echo
