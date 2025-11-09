#!/usr/bin/env bash
set -euo pipefail

echo "== UI Smoke Test =="

pushd "$(dirname "$0")/.." >/dev/null

echo "[1/3] Building frontend..."
pushd frontend >/dev/null
npm ci --silent
npm run -s build
test -f build/index.html && echo "  OK: build artifact present"
popd >/dev/null

echo "[2/3] Checking ops static mount path..."
if rg -n "APP.mount\(\"/\", StaticFiles\(directory=\"ops/static_ui\"" ops/ops_api.py >/dev/null; then
  echo "  OK: ops mounts SPA at /"
else
  echo "  ERR: ops does not mount static UI"
  exit 1
fi

echo "[3/3] Quick Prometheus/engine target check..."
if rg -n "hmm_engine_binance:8003" ops/observability/prometheus/prometheus.yml >/dev/null; then
  echo "  OK: Prometheus engine target present"
else
  echo "  WARN: missing engine target in Prometheus config"
fi

echo "UI smoke OK"
