#!/usr/bin/env bash
set -euo pipefail

echo "== Nautilus Starter Pack: Wiring Smoke Test =="

root_dir="$(cd "$(dirname "$0")" && pwd)"

fail=0

echo "[1/5] Checking docker-compose engine wiring..."
count_mode=$(rg -n "^\s*-\s*BINANCE_MODE=" docker-compose.yml | wc -l | tr -d ' ')
if [[ "$count_mode" -gt 1 ]]; then
  echo "  ERR: duplicate BINANCE_MODE entries in docker-compose.yml ($count_mode)"
  fail=1
else
  echo "  OK: BINANCE_MODE defined once"
fi

echo "[2/5] Scanning .env for risky secrets and unit mismatches..."
if [[ -f .env ]]; then
  # Secrets presence
  for key in BINANCE_API_KEY BINANCE_API_SECRET TELEGRAM_BOT_TOKEN DEX_PRIVATE_KEY; do
    if rg -n "^${key}=" .env >/dev/null; then
      val=$(grep -E "^${key}=" .env | head -1 | cut -d'=' -f2-)
      if [[ -n "$val" && "$val" != "" ]]; then
        echo "  WARN: $key present in tracked .env (rotate + remove from VCS)"
      fi
    fi
  done
  # Timeout units sanity (seconds expected by code)
  if rg -n "^BINANCE_API_TIMEOUT=\s*[0-9]{4,}" .env >/dev/null; then
    echo "  ERR: BINANCE_API_TIMEOUT appears to be milliseconds in .env (code expects seconds)"
    fail=1
  else
    echo "  OK: BINANCE_API_TIMEOUT not egregiously large in .env"
  fi
else
  echo "  NOTE: .env not found (ok for CI)"
fi

echo "[3/5] Validating Prometheus scrape targets match service names..."
if rg -n "hmm_engine_binance:8003" ops/observability/prometheus/prometheus.yml >/dev/null && \
   rg -n "hmm_engine_binance_exporter:8003" ops/observability/prometheus/prometheus.yml >/dev/null; then
  echo "  OK: Prometheus targets aligned with engine container names"
else
  echo "  ERR: Prometheus targets do not match engine container names"
  fail=1
fi

echo "[4/5] Running property test for order validity (if pytest available)..."
if command -v pytest >/dev/null 2>&1; then
  if ! pytest -q tests/property/test_never_invalid_order.py::test_never_submit_invalid_size_for_symbol; then
    echo "  ERR: property test failed"
    fail=1
  else
    echo "  OK: property test passed"
  fi
else
  echo "  NOTE: pytest not installed; skipping"
fi

echo "[5/5] Replay harness sanity check..."
python tools/replay_fills.py tests/fixtures/fills_btcusdt.json | rg -n '"equity":' >/dev/null && echo "  OK: replay produced summary" || { echo "  ERR: replay failed"; fail=1; }

if [[ "$fail" -ne 0 ]]; then
  echo "Smoke test FAILED"
  exit 1
fi
echo "All checks passed"

