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

: "${SKIP_DOCKER:=0}"
: "${SKIP_FRONTEND:=0}"
: "${SKIP_TESTS:=0}"
: "${SKIP_PIP_AUDIT:=0}"
: "${SKIP_BANDIT:=0}"
: "${SKIP_E2E:=1}"
: "${AUDIT_DEBUG:=1}"
: "${PYTEST_ADDOPTS:=}"
: "${AUDIT_STRICT:=0}"
: "${RUFF_TARGETS:=.}"
: "${RUFF_AUTOFIX_IGNORE:=E501}"
: "${BANDIT_TARGETS:=engine services}"
DEFAULT_NODE_FLAGS="--ignore-scripts --prefer-offline"
NODE_INSTALL_FLAGS="${NODE_INSTALL_FLAGS:-${NPM_INSTALL_FLAGS:-$DEFAULT_NODE_FLAGS}}"
LOG_DIR="$ROOT/audit/logs"
mkdir -p "$LOG_DIR"

if ! command -v docker >/dev/null 2>&1; then
  SKIP_DOCKER=1
fi

run_step() {
  local label="$1"
  shift
  echo "==> ${label}"
  "$@"
}

if command -v ruff >/dev/null 2>&1; then
  echo "[audit] ruff autofix (E/I) on: ${RUFF_TARGETS}"
  ruff check ${RUFF_TARGETS} --select E,I --ignore "${RUFF_AUTOFIX_IGNORE}" --fix \
    | tee "$LOG_DIR/ruff_autofix.log" || true

  echo "[audit] ruff report (F/B/TRY/BLE) on: ${RUFF_TARGETS}"
  set +e
  ruff check ${RUFF_TARGETS} --select F,B,TRY,BLE | tee "$LOG_DIR/ruff_report.txt"
  RC_RUFF=${PIPESTATUS[0]}
  set -e

  if [[ "${AUDIT_STRICT}" == "1" ]]; then
    if [[ ${RC_RUFF} -ne 0 ]]; then
      echo "[audit] ruff blocking (AUDIT_STRICT=1) — failing on remaining issues"
      exit 1
    fi
  else
    echo "[audit] ruff non-blocking (AUDIT_STRICT=0) — continuing to black/mypy/tests"
  fi
fi

run_step "python format check (black)" "${PYTHON_BIN}" -m black --check "$ROOT"
MYPY_TARGETS=()
DEFAULT_MYPY_TARGETS=(
  "engine/app.py"
  "ops/ui_api.py"
  "services/backtester/app/main.py"
  "services/data_ingester/app/main.py"
  "services/ml_service/app/main.py"
  "services/param_controller/app/main.py"
)
for target in "${DEFAULT_MYPY_TARGETS[@]}"; do
  path="$ROOT/$target"
  if [[ -f "$path" || -d "$path" ]]; then
    MYPY_TARGETS+=("$target")
  fi
done
if command -v mypy >/dev/null 2>&1; then
  if [[ "${#MYPY_TARGETS[@]}" -eq 0 ]]; then
    echo "[audit] mypy skipped; no Python targets found" | tee -a "$LOG_DIR/mypy.log"
  else
    MYPY_CMD=("${PYTHON_BIN}" -m mypy --explicit-package-bases "${MYPY_TARGETS[@]}")
    echo "==> python typecheck (mypy)"
    if ! "${MYPY_CMD[@]}" | tee "$LOG_DIR/mypy.log"; then
      echo "[audit] mypy reported issues (non-blocking); see $LOG_DIR/mypy.log"
    fi
  fi
fi

if [[ "$SKIP_TESTS" == "1" ]]; then
  echo "==> pytest smoke (skipped)"
else
  run_step "pytest smoke" env PYTHONWARNINGS=ignore::DeprecationWarning PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTEST_ADDOPTS="${PYTEST_ADDOPTS}" "${PYTHON_BIN}" -m pytest -q
fi

if [[ "$SKIP_PIP_AUDIT" == "1" ]]; then
  echo "==> pip-audit (skipped)"
else
  log_path="$LOG_DIR/pip_audit.txt"
  echo "==> pip-audit"
  if ! bash -c "set -euo pipefail; \"${PYTHON_BIN}\" -m pip_audit -r \"$ROOT/requirements.txt\" -r \"$ROOT/requirements-dev.txt\" | tee \"$log_path\""; then
    echo "pip-audit found vulnerabilities; see $log_path" >&2
    exit 1
  fi
fi

if [[ "$SKIP_BANDIT" == "1" ]]; then
  echo "==> bandit (skipped)"
else
  bandit_log="$LOG_DIR/bandit.txt"
  echo "==> bandit"
  if ! bash -c "set -euo pipefail; bandit -r ${BANDIT_TARGETS} -x tests,docs,frontend -f screen -q -n 1 | tee \"$bandit_log\""; then
    echo "bandit reported findings; see $bandit_log" >&2
    exit 1
  fi
fi

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
      run_step "docker compose config ($profile)" bash -c "docker compose -f \"$ROOT/docker-compose.yml\" -f \"$ROOT/$profile\" config >/dev/null"
    fi
  done
fi

echo "==> audit complete"
