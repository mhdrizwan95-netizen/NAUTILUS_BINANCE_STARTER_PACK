#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> python lint (ruff)"
python -m ruff check "$ROOT"

echo "==> python format check (black)"
python -m black --check "$ROOT"

echo "==> python typecheck (mypy)"
python -m mypy engine ops services src tests

echo "==> pytest smoke"
PYTHONWARNINGS=ignore::DeprecationWarning pytest -q

echo "==> pip-audit"
pip-audit -r "$ROOT/requirements.txt" -r "$ROOT/requirements-dev.txt"

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
