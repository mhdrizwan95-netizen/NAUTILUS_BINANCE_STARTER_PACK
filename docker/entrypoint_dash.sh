#!/usr/bin/env bash
set -euo pipefail
: "${PROMETHEUS_MULTIPROC_DIR:=/tmp/prom_multiproc}"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
# wipe stale shards; safe for Prom multiprocess
rm -f "${PROMETHEUS_MULTIPROC_DIR}/"*.db 2>/dev/null || true
exec /usr/bin/tini -- uvicorn dashboard.app:APP --host 0.0.0.0 --port 8002 --workers 2
