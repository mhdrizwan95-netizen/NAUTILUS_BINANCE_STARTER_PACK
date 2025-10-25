#!/usr/bin/env bash
set -euo pipefail

MAIN_COMPOSE="docker compose"
OBS_COMPOSE="docker compose -f ops/observability/docker-compose.observability.yml"

echo "🔍 Checking engine_kraken_exporter container status..."
$MAIN_COMPOSE ps engine_kraken_exporter

PROM_CONTAINER=$($OBS_COMPOSE ps -q prometheus || true)
if [[ -z "${PROM_CONTAINER}" ]]; then
  echo "⚠️ Prometheus container not running (obs stack). Start it with 'make up-obs' and rerun."
  exit 1
fi

echo "🔗 Verifying DNS resolution from Prometheus container..."
docker exec "$PROM_CONTAINER" getent hosts engine_kraken_exporter

echo "🌐 Curling exporter metrics from Prometheus container..."
docker exec "$PROM_CONTAINER" curl -fsS --max-time 3 http://engine_kraken_exporter:8003/metrics >/tmp/kraken_exporter_metrics.$$ && {
  echo "✅ Metrics endpoint reachable (sample below):"
  head -n 5 /tmp/kraken_exporter_metrics.$$
  rm /tmp/kraken_exporter_metrics.$$
}

echo "📈 Querying Prometheus for exporter heartbeat..."
curl -fsS -G --data-urlencode 'query=time()-metrics_heartbeat{job="engine_kraken_exporter"}' \
  "${PROM_URL:-http://localhost:9090}"/api/v1/query | jq '.data.result'

echo "✅ Connectivity checks completed."
