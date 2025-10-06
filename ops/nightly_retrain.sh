#!/usr/bin/env bash
set -euo pipefail
ROOT="${ROOT:-$(pwd)}"
ML="http://127.0.0.1:8010"

# 1) Train on recent slice (your pipeline should prepare sequences)
TAG=$(curl -s -X POST "$ML/train" -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT","feature_sequences":[[[1,2,3],[2,3,4]]]} ' | python -c 'import sys,json; print(json.load(sys.stdin).get("tag",""))')
if [[ -z "$TAG" ]]; then echo "Train failed"; exit 1; fi
echo "New model tag: $TAG"

# 2) Load but do not promote
curl -s -X POST "$ML/load" -H "Content-Type: application/json" -d "{\"tag\":\"$TAG\"}" >/dev/null

# 3) Canary on recent data
python ops/canary_sim.py --tag "$TAG" --config backtests/configs/crypto_spot.yaml > data/processed/canary_${TAG}.log 2>&1 || true

# 4) Simple gate: check log heuristics (replace with real KPIs)
if grep -q "Done. PnL=" "data/processed/canary_${TAG}.log"; then
  echo "Canary OK, promoting $TAG"
  curl -s -X POST "$ML/promote" -H "Content-Type: application/json" -d "{\"tag\":\"$TAG\"}"
else
  echo "Canary failed; keeping current active."
fi
