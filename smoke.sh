#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nautilus_smoke}"

:
  "${SECRETS_DIR:?Set SECRETS_DIR to directory containing ops_api_token, grafana_admin_password, binance_api_key, binance_api_secret}"

OPS_SECRET_FILE="${SECRETS_DIR}/ops_api_token"
GRAFANA_SECRET_FILE="${SECRETS_DIR}/grafana_admin_password"
BINANCE_KEY_FILE="${SECRETS_DIR}/binance_api_key"
BINANCE_SECRET_FILE="${SECRETS_DIR}/binance_api_secret"

if [[ ! -s "${OPS_SECRET_FILE}" ]]; then
  echo "ops_api_token secret missing or empty at ${OPS_SECRET_FILE}" >&2
  exit 1
fi

if [[ ! -s "${GRAFANA_SECRET_FILE}" ]]; then
  echo "grafana_admin_password secret missing or empty at ${GRAFANA_SECRET_FILE}" >&2
  exit 1
fi

if [[ ! -s "${BINANCE_KEY_FILE}" ]]; then
  echo "binance_api_key secret missing or empty at ${BINANCE_KEY_FILE}" >&2
  exit 1
fi

if [[ ! -s "${BINANCE_SECRET_FILE}" ]]; then
  echo "binance_api_secret missing or empty at ${BINANCE_SECRET_FILE}" >&2
  exit 1
fi

export GF_SECURITY_ADMIN_USER="${GF_SECURITY_ADMIN_USER:-grafana_admin}"

COMPOSE_FILES=(
  -f "${ROOT_DIR}/docker-compose.yml"
  -f "${ROOT_DIR}/ops/observability/docker-compose.observability.yml"
  -f "${ROOT_DIR}/compose.override.yaml"
  -f "${ROOT_DIR}/compose.hardening.override.yaml"
)

cleanup() {
  docker compose "${COMPOSE_FILES[@]}" down --remove-orphans
}
trap cleanup EXIT

docker compose "${COMPOSE_FILES[@]}" config > /tmp/compose.hardening.rendered.yml
docker compose "${COMPOSE_FILES[@]}" up -d ops grafana engine_binance

echo "Waiting for ops service readiness..."
OPS_READY=0
for attempt in {1..20}; do
  if docker compose "${COMPOSE_FILES[@]}" exec -T ops curl -fsS --max-time 5 http://127.0.0.1:8002/readyz | jq -e '.ok == true' >/dev/null; then
    OPS_READY=1
    echo "Ops API ready (attempt ${attempt})."
    break
  fi
  echo "ops readiness attempt ${attempt}/20 failed; sleeping..."
  sleep 3
done

if [[ "${OPS_READY}" -ne 1 ]]; then
  echo "Ops API failed readiness checks." >&2
  exit 4
fi

echo "Waiting for engine readiness..."
ENGINE_READY=0
for attempt in {1..20}; do
  if docker compose "${COMPOSE_FILES[@]}" exec -T engine_binance curl -fsS --max-time 5 http://127.0.0.1:8003/readyz | jq -e '.ok == true' >/dev/null; then
    ENGINE_READY=1
    echo "Engine ready (attempt ${attempt})."
    break
  fi
  echo "engine readiness attempt ${attempt}/20 failed; sleeping..."
  sleep 3
done

if [[ "${ENGINE_READY}" -ne 1 ]]; then
  echo "Engine readiness checks failed." >&2
  exit 6
fi

echo "Checking Grafana admin credentials..."
GRAFANA_READY=0
for attempt in {1..20}; do
  if docker compose "${COMPOSE_FILES[@]}" exec -T grafana curl -fsS --max-time 5 http://127.0.0.1:3000/api/health | grep -q '\"database\": \"ok\"'; then
    GRAFANA_READY=1
    echo "Grafana healthy (attempt ${attempt})."
    break
  fi
  echo "grafana readiness attempt ${attempt}/20 failed; sleeping..."
  sleep 3
done

if [[ "${GRAFANA_READY}" -ne 1 ]]; then
  echo "Grafana admin status check failed." >&2
  exit 5
fi

echo "smoke.sh: ops, engine (exporter role), and grafana healthy with hardened secrets."
