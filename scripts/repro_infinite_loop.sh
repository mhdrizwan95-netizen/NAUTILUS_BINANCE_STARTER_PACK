#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PW_BASE_URL="${PW_BASE_URL:-http://localhost:8002}"

cd "$FRONTEND_DIR"

echo "[repro] targeting $PW_BASE_URL (set PW_BASE_URL to override)"

timeout 60s bash -c "PW_BASE_URL='$PW_BASE_URL' npx playwright test e2e/dashboard.spec.ts --project=chromium --grep 'should load the dashboard with all components'" || true

echo "==== Playwright error context ===="
if [ -d test-results ]; then
  find test-results -name error-context.md -print -exec cat {} \;
fi
