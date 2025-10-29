#!/usr/bin/env bash
set -euo pipefail

echo "[clean] Removing legacy HMM skeleton and live-runner stub…"

git rm -r --ignore-unmatch strategies/hmm_policy || true
git rm --ignore-unmatch ops/run_live.py || true

echo "[clean] Searching for references to 'hmm_policy' or 'run_live'…"
rg -n --glob '!*venv*' --glob '!*.ipynb' '(hmm_policy|run_live)' || true

echo "[clean] Done. Review the printed lines (if any), then commit:"
echo "  git commit -m 'chore: remove legacy HMM skeleton and obsolete live runner'"
