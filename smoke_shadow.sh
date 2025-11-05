#!/usr/bin/env bash
set -euo pipefail

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    docker compose -f docker-compose.yml -f compose.override.yaml config > "$tmp"
  elif docker-compose version >/dev/null 2>&1; then
    docker-compose -f docker-compose.yml -f compose.override.yaml config > "$tmp"
  else
    cat docker-compose.yml compose.override.yaml > "$tmp"
  fi
else
  cat docker-compose.yml compose.override.yaml > "$tmp"
fi

echo "[shadow-smoke] verifying trading disabled"
grep -Eq 'TRADING_ENABLED(:\s+"false"|=false)' "$tmp"

echo "[shadow-smoke] verifying strategy dry-run enabled"
grep -Eq 'STRATEGY_DRY_RUN(:\s+"true"|=true)' "$tmp"

echo "[shadow-smoke] verifying scalper maker shadow enabled"
grep -Eq 'SCALP_MAKER_SHADOW(:\s+"true"|=true)' "$tmp"

echo "[shadow-smoke] verifying executor disabled"
grep -Eq 'ENABLE_EXECUTION(:\s+"false"|=false)' "$tmp"

echo "[shadow-smoke] config looks good"
