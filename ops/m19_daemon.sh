#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source ../.venv/bin/activate || true
INTERVAL="${1:-300}"   # default 5 minutes
echo "[M19] Daemon starting (every ${INTERVAL}s)"
while true; do
  python ops/m19_scheduler.py || true
  sleep "$INTERVAL"
done
