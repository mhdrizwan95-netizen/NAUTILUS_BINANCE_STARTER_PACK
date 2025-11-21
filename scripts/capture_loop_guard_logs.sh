#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT="${PW_UI_PORT:-4176}"
HOST="${PW_UI_HOST:-127.0.0.1}"
DEV_LOG="${DEV_LOG:-/tmp/loop_guard_vite.log}"
CONSOLE_LOG="${CONSOLE_LOG:-/tmp/loop_guard_console.log}"

cleanup() {
  if [[ -n "${DEV_PID:-}" ]]; then
    kill "$DEV_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[loop guard] starting Vite dev server on ${HOST}:${PORT}"
cd "$FRONTEND_DIR"
PORT=$PORT npm run dev -- --host "$HOST" --port "$PORT" >"$DEV_LOG" 2>&1 &
DEV_PID=$!
sleep 2

echo "[loop guard] capturing console logs to $CONSOLE_LOG"
PW_TARGET="http://${HOST}:${PORT}/" PW_SAMPLE_MS=8000 node scripts/collect_loop_guard_logs.mjs >"$CONSOLE_LOG" 2>&1 || true

echo "=== Console sample (${CONSOLE_LOG}) ==="
cat "$CONSOLE_LOG"
echo "=== Dev server log (${DEV_LOG}) ==="
tail -n 50 "$DEV_LOG" || true
