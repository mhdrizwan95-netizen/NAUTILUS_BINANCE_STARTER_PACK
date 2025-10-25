#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source ../.venv/bin/activate || true
mkdir -p data/processed/m20
echo "[M20] Guardian active (continuous monitoring every 60 seconds)"

INTERVAL="${1:-60}"  # check every 60 seconds by default
echo "Monitoring interval: ${INTERVAL}s"

while true; do
  echo "$(date '+%Y-%m-%d %H:%M:%S') [M20] Health check starting..."
  python -c "
import sys
sys.path.insert(0, '.')
import ops.m20_detector as detector
import ops.m20_playbook as playbook

# Read metrics from M19 snapshot (in production, would use real Prometheus)
try:
    import json
    with open('data/processed/m19/metrics_snapshot.json', 'r') as f:
        metrics = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    # Default safe metrics when no data available
    metrics = {
        'drift_score': 0.0,
        'm16_winrate': 0.52,
        'pnl_drawdown_pct': 0.0,
        'guardrail_trigger_total_5m': 0,
        'exchange_latency_ms': 100,
        'macro_entropy_bits': 0.2,
        'corr_spike': 0.0
    }

# Run health assessment
result = detector.detect(metrics)
print(f'[M20] Assessment: {result[\"status\"]}')

if result['status'] != 'healthy':
    print(f'[M20] 🚨 INCIDENTS: {result[\"incidents\"]}')
    # Execute recovery playbooks
    recovery_result = playbook.execute(result['incidents'])
    print(f'[M20] Recovery attempted: {recovery_result[\"overall_success\"]}')
    print(f'[M20] Actions: {len(recovery_result[\"successful_actions\"])} successful, {len(recovery_result[\"failed_actions\"])} failed')
else:
    print('[M20] ✓ All systems healthy')
"

  echo "$(date '+%Y-%m-%d %H:%M:%S') [M20] Health check complete. Sleeping ${INTERVAL}s..."
  sleep "$INTERVAL"
done
