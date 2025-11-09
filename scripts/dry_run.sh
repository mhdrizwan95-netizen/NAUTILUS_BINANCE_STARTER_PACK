#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DRY_RUN="${DRY_RUN:-1}"
export OPS_API_TOKEN="${OPS_API_TOKEN:-dry-run-token}"
detach="${DRY_RUN_DETACH:-0}"
env_file="${DRY_RUN_ENV_FILE:-$ROOT/.env.dryrun}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for dry-run; install Docker Desktop or Colima first." >&2
  exit 1
fi

if [[ ! -f "$env_file" ]]; then
  echo "==> generating ${env_file} from env.example (safe defaults only)"
  cp "$ROOT/env.example" "$env_file"
  {
    echo ""
    echo "DRY_RUN=1"
    echo "STRATEGY_DRY_RUN=true"
    echo "OPS_API_TOKEN=dry-run-token"
  } >>"$env_file"
fi

cd "$ROOT"

AVAILABLE_SERVICES="$(docker compose --env-file "$env_file" config --services | tr '\n' ' ')"

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

cleanup() {
  docker compose --env-file "$env_file" stop "${SERVICES[@]}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> staging services (DRY_RUN=${DRY_RUN})"
docker compose --env-file "$env_file" up --no-start "${SERVICES[@]}"
docker compose --env-file "$env_file" create "${SERVICES[@]}"

echo "==> starting services"
docker compose --env-file "$env_file" start "${SERVICES[@]}"

echo "==> running health checks"
HEALTH_FLAGS=(--fail --silent --retry 10 --retry-delay 2 --retry-all-errors --max-time 10 --retry-connrefused)
if echo " ${SERVICES[*]} " | grep -q " ops "; then
  curl "${HEALTH_FLAGS[@]}" http://localhost:8002/health >/dev/null
fi
if echo " ${SERVICES[*]} " | grep -q " engine_binance "; then
  curl "${HEALTH_FLAGS[@]}" http://localhost:8003/readyz >/dev/null
fi
if echo " ${SERVICES[*]} " | grep -q " engine_binance_exporter "; then
  curl "${HEALTH_FLAGS[@]}" http://localhost:9103/health >/dev/null
fi

if [[ "$detach" == "1" ]]; then
  echo "==> dry run checks passed (services stopped on exit)"
  exit 0
fi

echo "==> dry run services running (Ctrl+C to stop via trap)"
while true; do sleep 60; done
