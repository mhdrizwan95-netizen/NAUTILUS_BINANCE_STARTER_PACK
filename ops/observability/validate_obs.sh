#!/usr/bin/env bash
set -uo pipefail

PROM_URL="${PROM_URL:-http://localhost:9090}"
CHECKS=0
FAILS=0
SKIPS=0

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
  # Protect against jq errors under 'set -e'; treat as zero results
  if ! result=$(jq '.data.result | length' <<<"${response}" 2>/dev/null); then
    result=0
  fi
  if [[ "${result}" -gt 0 ]]; then
    echo "OK (got ${result} results)"
  else
    echo "FAIL (no results)"
    (( FAILS++ ))
  fi
  (( CHECKS++ ))
}

# Optional check that is skipped if a given job label does not exist
function check_optional_for_job {
  local desc="$1"; shift
  local query="$1"; shift
  local job_name="$1"
  echo -n "  → ${desc} : "
  local jobs_json
  if ! jobs_json=$(curl -fsS "${PROM_URL}/api/v1/label/job/values"); then
    echo "SKIP (cannot list jobs)"
    (( SKIPS++ ))
    return
  fi
  if ! jq -e --arg J "$job_name" '.data | index($J)' >/dev/null 2>&1 <<<"${jobs_json}"; then
    echo "SKIP (job '${job_name}' absent)"
    (( SKIPS++ ))
    return
  fi
  # Fall back to normal check
  local response
  if ! response=$(curl -fsS -G --data-urlencode "query=${query}" "${PROM_URL}/api/v1/query"); then
    echo "FAIL (query error)"
    (( FAILS++ ))
    (( CHECKS++ ))
    return
  fi
  local result
  if ! result=$(jq '.data.result | length' <<<"${response}" 2>/dev/null); then
    result=0
  fi
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
check "Raw metric: exposure_usd"                   'exposure_usd'
check "Recording rule: realized pnl aggregate"     'trading:pnl_realized_usd'
check "Aggregate exposure by job (sum)"            'sum by(job) (exposure_usd)'
check "Governance stat: max notional"              'max_notional_usdt'
check "Flag: trading enabled"                      'trading_enabled'

echo
echo "Checked ${CHECKS} queries: ${FAILS} failures, ${SKIPS} skipped"
if [[ "${FAILS}" -gt 0 ]]; then
  echo "❌ ERROR: Some queries failed → observability pipeline may have mis-aligned queries / no data"
  echo "💡 Fix: Check credentials, target health, recording rules, or label consistency"
  exit 1
else
  echo "✅ SUCCESS: All observability queries validated - dashboards ready!"
  exit 0
fi
