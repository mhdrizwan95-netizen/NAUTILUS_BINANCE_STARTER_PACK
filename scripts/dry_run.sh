#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DRY_RUN="${DRY_RUN:-1}"
export OPS_API_TOKEN="${OPS_API_TOKEN:-dry-run-token}"
detach="${DRY_RUN_DETACH:-0}"

cd "$ROOT"

AVAILABLE_SERVICES="$(docker compose config --services | tr '\n' ' ')"

want_services=(
  ops
  prometheus
  grafana
  engine_binance_exporter
  engine_binance
)

SERVICES=()
for svc in "${want_services[@]}"; do
  if echo " ${AVAILABLE_SERVICES} " | grep -q " ${svc} "; then
    SERVICES+=("${svc}")
  fi
done

if [[ "${#SERVICES[@]}" -eq 0 ]]; then
  echo "No matching services found for dry run" >&2
  exit 1
fi

trap 'docker compose stop "${SERVICES[@]}" >/dev/null 2>&1 || true' EXIT

echo "==> staging services (DRY_RUN=${DRY_RUN})"
docker compose up --no-start "${SERVICES[@]}"
docker compose create "${SERVICES[@]}"

echo "==> starting services"
docker compose start "${SERVICES[@]}"

echo "==> running health checks"
if echo " ${SERVICES[*]} " | grep -q " ops "; then
  curl -fsS --retry 5 --retry-delay 2 http://localhost:8002/health >/dev/null
fi
if echo " ${SERVICES[*]} " | grep -q " engine_binance "; then
  curl -fsS --retry 5 --retry-delay 2 http://localhost:8003/health >/dev/null
fi
if echo " ${SERVICES[*]} " | grep -q " engine_binance_exporter "; then
  curl -fsS --retry 5 --retry-delay 2 http://localhost:9103/health >/dev/null
fi

if [[ "$detach" == "1" ]]; then
  echo "==> dry run checks passed (services stopped on exit)"
  exit 0
fi

echo "==> dry run services running (Ctrl+C to stop via trap)"
while true; do sleep 60; done
