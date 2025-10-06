#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source ../.venv/bin/activate || true
mkdir -p data/dreams
INTERVAL="${1:-1800}"  # 30 minutes by default
echo "[M23] Dream daemon activated (interval=${INTERVAL}s)"
echo "[M23] Beginning ancestral resurrection cycles..."

while true; do
  echo "$(date '+%Y-%m-%d %H:%M:%S') [M23] Dream cycle commencing..."
  start_time=$(date +%s)

  # Execute dream engine (will only run if models available)
  python ops/m23_dream_engine.py || {
    echo "[M23] Dream cycle encountered error"
    sleep 60  # Brief pause on error
  }

  # Generate visualizations every few cycles (every ~3 hours)
  if [[ $(( ($(date +%s) / 1800) % 6 )) -eq 0 ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [M23] Generating dream visualization updates..."
    python ops/m23_dream_viz.py 2>/dev/null || {
      echo "[M23] Visualization update failed"
    }
  fi

  # Calculate cycle timing
  end_time=$(date +%s)
  cycle_duration=$((end_time - start_time))
  echo "$(date '+%Y-%m-%d %H:%M:%S') [M23] Dream cycle complete (${cycle_duration}s)"

  # Wait for next cycle
  sleep_remaining=$((INTERVAL - cycle_duration))
  if [[ $sleep_remaining -gt 0 ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [M23] Entering rest state for ${sleep_remaining}s..."
    sleep "$sleep_remaining"
  else
    echo "[M23] ⚡ Dream cycle ran long - skipping rest phase"
  fi

done
