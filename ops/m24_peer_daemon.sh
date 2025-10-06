#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source ../.venv/bin/activate || true
INTERVAL="${1:-900}" # 15 minutes
echo "[M24] Peer sync running every ${INTERVAL}s"
while true; do
  python ops/m24_peer_client.py || true
  sleep "$INTERVAL"
done
