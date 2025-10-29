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
if [[ -n "${QUICKCHECK_CSV:-}" && -f "$QUICKCHECK_CSV" ]]; then
  python scripts/backtest_hmm.py --csv "$QUICKCHECK_CSV" --model "${QUICKCHECK_MODEL:-engine/models/hmm_policy.pkl}" --symbol "${QUICKCHECK_SYMBOL:-BTCUSDT}" --quote "${QUICKCHECK_QUOTE:-100}" --out "${QUICKCHECK_OUT:-reports/quickcheck.json}" || true
  ls -lh reports/quickcheck.json reports/backtest_equity.csv 2>/dev/null || true
else
  echo "(skip) QUICKCHECK_CSV not set - provide path to run the smoke backtest."
fi

echo "== DASH METRICS SNAPSHOT =="
curl -s "$DASH/metrics" | head -n 20

echo "== OPS STATUS =="
curl -s "$OPS/status" && echo

echo "== CANARY & PROMOTE =="
python ops/canary_sim.py --tag "$TAG" --config backtests/configs/crypto_spot.yaml || true
curl -s -X POST "$ML/promote" -H "Content-Type: application/json" -d "{\"tag\":\"$TAG\"}" && echo
curl -s "$ML/models" && echo
