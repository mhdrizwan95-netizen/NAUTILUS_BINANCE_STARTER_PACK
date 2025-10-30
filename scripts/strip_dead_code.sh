#!/usr/bin/env bash
set -euo pipefail

echo "[strip] Removing known-dead paths…"
git rm --ignore-unmatch run_backtest.py ops/run_backtest.py scripts/run_backtest.py >/dev/null 2>&1 || true
git rm -r --ignore-unmatch ops/experiments ops/legacy scripts/experiments scripts/legacy scripts/backtest* scripts/sim* tools/backtest* bench/backtest* >/dev/null 2>&1 || true

echo "[strip] Searching for milestone tags (M1....M24)…"
rg -n --iglob '!**/{.git,venv,node_modules,dist,build,assets,docs}/**' -g '*.{py,ts,js,go,rs,sh,yaml,yml,toml,ini}' \
   -e '\bM[1-9]\b' -e '\bM1[0-9]\b' -e '\bM2[0-4]\b' || true

echo "[strip] Done. Review matches above and remove/modernize any leftover blocks."
