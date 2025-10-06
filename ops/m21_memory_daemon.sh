#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source ../.venv/bin/activate || true
mkdir -p data/memory_vault
INTERVAL="${1:-600}"  # every 10 minutes by default
echo "[M21] Memory daemon started (interval=${INTERVAL}s)"
echo "Will automatically archive new model generations for lineage tracking"

while true; do
  echo "$(date '+%Y-%m-%d %H:%M:%S') [M21] Checking for new generations to archive..."

  # Set generation context based on current state
  if [[ -n "${GENERATION_TYPE:-}" ]]; then
    echo "Current generation context: $GENERATION_TYPE"
  fi

  # Run the memory manager (it will only archive if new models are found)
  python ops/m21_memory_manager.py 2>/dev/null || {
    echo "❌ Memory manager execution failed"
    sleep 30  # Brief pause before retry
  }

  # Periodically generate visualizations (every 3rd run ~30 minutes)
  if [[ $(( (($(date +%s) / 600)) % 3 )) -eq 0 ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [M21] Generating fresh lineage visualizations..."
    python ops/m21_memory_viz.py 2>/dev/null || {
      echo "⚠️  Visualization generation failed"
    }
  fi

  echo "$(date '+%Y-%m-%d %H:%M:%S') [M21] Archive cycle complete. Sleeping ${INTERVAL}s..."
  sleep "$INTERVAL"
done
