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

SKIP_DOCKER="${SKIP_DOCKER:-0}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"
SKIP_TESTS="${SKIP_TESTS:-0}"
DEFAULT_NODE_FLAGS="--ignore-scripts --prefer-offline"
NODE_INSTALL_FLAGS="${NODE_INSTALL_FLAGS:-${NPM_INSTALL_FLAGS:-$DEFAULT_NODE_FLAGS}}"

if ! command -v docker >/dev/null 2>&1; then
  SKIP_DOCKER=1
fi

run_step() {
  local label="$1"
  shift
  echo "==> ${label}"
  "$@"
}

run_step "python lint (ruff)" "${PYTHON_BIN}" -m ruff check "$ROOT"
run_step "python format check (black)" "${PYTHON_BIN}" -m black --check "$ROOT"
run_step "python typecheck (mypy)" "${PYTHON_BIN}" -m mypy engine ops services src tests

if [[ "$SKIP_TESTS" == "1" ]]; then
  echo "==> pytest smoke (skipped)"
else
  run_step "pytest smoke" env PYTHONWARNINGS=ignore::DeprecationWarning "${PYTHON_BIN}" -m pytest -q
fi

run_step "pip-audit" "${PYTHON_BIN}" -m pip_audit -r "$ROOT/requirements.txt" -r "$ROOT/requirements-dev.txt"
run_step "bandit" bandit -q -r engine ops services src

if [[ "$SKIP_FRONTEND" == "1" ]]; then
  echo "==> frontend checks (skipped)"
else
  run_step "frontend install" bash -c "cd \"$ROOT/frontend\" && npm ci ${NODE_INSTALL_FLAGS}"
  run_step "frontend lint" bash -c "cd \"$ROOT/frontend\" && npm run lint"
  run_step "frontend typecheck" bash -c "cd \"$ROOT/frontend\" && npm run typecheck"
  if [[ "$SKIP_TESTS" == "1" ]]; then
    echo "==> frontend unit tests (skipped)"
  else
    run_step "frontend unit tests" bash -c "cd \"$ROOT/frontend\" && npm run test:ci"
  fi
  run_step "npm audit (non-blocking on advisories below high)" bash -c "cd \"$ROOT/frontend\" && (npm audit --audit-level=high || true)"
fi

if [[ "$SKIP_DOCKER" == "1" ]]; then
  echo "==> docker compose config validation (skipped)"
else
  run_step "docker compose config validation" bash -c "docker compose config >/dev/null"
  for profile in compose.backfill.yml compose.backtest.yml compose.ml.yml compose.autotrain.yml; do
    if [[ -f "$ROOT/$profile" ]]; then
      run_step "docker compose config ($profile)" bash -c "docker compose -f \"$ROOT/$profile\" config >/dev/null"
    fi
  done
fi

echo "==> audit complete"
