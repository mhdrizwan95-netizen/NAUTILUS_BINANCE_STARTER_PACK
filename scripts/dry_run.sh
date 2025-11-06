#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DRY_RUN="${DRY_RUN:-1}"
export OPS_API_TOKEN="${OPS_API_TOKEN:-dry-run-token}"
detach="${DRY_RUN_DETACH:-0}"

cd "$ROOT"

readonly SERVICES=(
  ops
  prometheus
  grafana
  engine_binance_exporter
  engine_binance
)

trap 'docker compose stop "${SERVICES[@]}" >/dev/null 2>&1 || true' EXIT

echo "==> staging services (DRY_RUN=${DRY_RUN})"
docker compose up --no-start "${SERVICES[@]}"
docker compose create "${SERVICES[@]}"

echo "==> starting services"
docker compose start "${SERVICES[@]}"

echo "==> running health checks"
curl -fsS --retry 5 --retry-delay 2 http://localhost:8002/health >/dev/null
curl -fsS --retry 5 --retry-delay 2 http://localhost:8003/health >/dev/null
curl -fsS --retry 5 --retry-delay 2 http://localhost:9103/health >/dev/null

if [[ "$detach" == "1" ]]; then
  echo "==> dry run checks passed (services stopped on exit)"
  exit 0
fi

echo "==> dry run services running (Ctrl+C to stop via trap)"
while true; do sleep 60; done
