#!/usr/bin/env bash
set -euo pipefail

PROM_URL="${PROM_URL:-http://localhost:9090}"
CHECKS=0
FAILS=0

function check {
  local desc="$1"
  local query="$2"
  echo -n "  → ${desc} : "
  local response
  if ! response=$(curl -fsS -G --data-urlencode "query=${query}" "${PROM_URL}/api/v1/query"); then
    echo "FAIL (query error)"
    (( FAILS++ ))
    (( CHECKS++ ))
    return
  fi
  local result
  result=$(jq '.data.result | length' <<<"${response}")
  if [[ "${result}" -gt 0 ]]; then
    echo "OK (got ${result} results)"
  else
    echo "FAIL (no results)"
    (( FAILS++ ))
  fi
  (( CHECKS++ ))
}

echo "Starting Prometheus observability pipeline validation against ${PROM_URL}"
echo

check "Recording rule: orders_rate_1m"             'trading:orders_rate_1m'
check "Raw metric: exposure_usd"                     'exposure_usd'
check "Raw metric: equity_usd for engine_ibkr (job filter)" 'equity_usd{job="engine_ibkr"}'
check "Raw metric: equity_usd for engine_kraken (job filter)" 'equity_usd{job="engine_kraken"}'
check "Recording rule: realized pnl aggregate"       'trading:pnl_realized_usd'
check "Aggregate exposure by job (sum)"              'sum by(job) (exposure_usd)'
check "Governance stat: max notional"                'max_notional_usdt'
check "Flag: trading enabled"                        'trading_enabled'

echo
echo "Checked ${CHECKS} queries: ${FAILS} failures"
if [[ "${FAILS}" -gt 0 ]]; then
  echo "❌ ERROR: Some queries failed → observability pipeline may have mis-aligned queries / no data"
  echo "💡 Fix: Check credentials, target health, recording rules, or label consistency"
  exit 1
else
  echo "✅ SUCCESS: All observability queries validated - dashboards ready!"
  exit 0
fi
