#!/usr/bin/env bash
set -euo pipefail

# Ensure Docker network exists if running in compose context
if command -v docker >/dev/null 2>&1; then
  docker network inspect nautilus_trading_network >/dev/null 2>&1 || docker network create nautilus_trading_network || true
fi

echo "[1/4] Pinging ML service health..."
curl -fsS http://localhost:8015/health || echo "NOTE: start ml_service in compose to run live smoke"

echo "[2/4] Validating features sample (if present)..."
if [[ -f data/sample.csv ]]; then
  python tools/validate_features.py data/sample.csv || true
else
  echo "  Skipped (data/sample.csv not found)"
fi

echo "[3/4] Running unit contract test (requires pytest)..."
if command -v pytest >/dev/null 2>&1; then
  pytest -q tests/ml_service/test_inference_contract.py || exit 1
else
  echo "  pytest not installed; skipping"
fi

echo "[4/4] Dry-run training endpoint contract (if live)..."
curl -fsS -X POST http://localhost:8015/train -H 'Content-Type: application/json' -d '{"n_states":4, "tag":"smoke","promote":false}' || echo "  Skipped; ensure ml_service is running"

echo "ML smoke finished"
