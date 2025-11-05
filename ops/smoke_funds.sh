#!/usr/bin/env bash
set -euo pipefail

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

echo "[smoke] running offline rebalance preview"
python3 ops/rebalance.py --offline --output "$tmp_dir/allocation.json" > "$tmp_dir/summary.json"

echo "[smoke] validating allocation JSON shape"
python3 - <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
result_path = Path(sys.argv[2])

summary = json.loads(summary_path.read_text())
result = json.loads(result_path.read_text())

assert "models" in summary, "summary missing models block"
assert "total_allocated" in summary, "summary missing total_allocated"
assert isinstance(result.get("final_quotas"), dict), "final_quotas missing"
assert result.get("equity", 0) >= 0, "equity must be non-negative"
print("[smoke] allocation summary OK")
PY "$tmp_dir/summary.json" "$tmp_dir/allocation.json"

echo "[smoke] completed successfully"
