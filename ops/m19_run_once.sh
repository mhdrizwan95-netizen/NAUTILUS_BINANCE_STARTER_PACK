#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source ../.venv/bin/activate || true
python ops/m19_scheduler.py
