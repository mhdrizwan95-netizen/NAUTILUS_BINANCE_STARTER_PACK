#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="${PYTHON}"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "python interpreter not found" >&2
  exit 1
fi

echo "==> python lint (ruff)"
PY_RUFF_TARGETS=(
  "$ROOT/engine/app.py"
  "$ROOT/ops/ops_api.py"
  "$ROOT/services/data_ingester/app/main.py"
  "$ROOT/services/ml_service/app/main.py"
  "$ROOT/services/param_controller/app/main.py"
  "$ROOT/shared/dry_run.py"
)
"${PYTHON_BIN}" -m ruff check "${PY_RUFF_TARGETS[@]}"

echo "==> python format check (black)"
"${PYTHON_BIN}" -m black --check "$ROOT"

echo "==> python typecheck (mypy)"
"${PYTHON_BIN}" -m mypy engine ops services src tests

echo "==> pytest smoke"
PYTHONWARNINGS=ignore::DeprecationWarning "${PYTHON_BIN}" -m pytest -q

echo "==> pip-audit"
"${PYTHON_BIN}" -m pip_audit -r "$ROOT/requirements.txt" -r "$ROOT/requirements-dev.txt"

echo "==> bandit"
bandit -q -r engine ops services src

echo "==> frontend install"
(cd "$ROOT/frontend" && npm ci --ignore-scripts)

echo "==> frontend lint"
(cd "$ROOT/frontend" && npm run lint)

echo "==> frontend typecheck"
(cd "$ROOT/frontend" && npm run typecheck)

echo "==> frontend unit tests"
(cd "$ROOT/frontend" && npm run test:ci)

echo "==> npm audit (non-blocking on advisories below high)"
(cd "$ROOT/frontend" && npm audit --audit-level=high || true)

echo "==> docker compose config validation"
docker compose config >/dev/null

for profile in compose.backfill.yml compose.backtest.yml compose.ml.yml compose.autotrain.yml; do
  if [[ -f "$ROOT/$profile" ]]; then
    docker compose -f "$ROOT/$profile" config >/dev/null
  fi
done

echo "==> audit complete"
