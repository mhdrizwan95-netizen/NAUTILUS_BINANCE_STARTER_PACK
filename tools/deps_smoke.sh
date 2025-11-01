#!/usr/bin/env bash
set -euo pipefail

echo "[Deps Smoke] Python version:"; python -V
echo "[Deps Smoke] Key package versions:"
python - <<'PY'
import importlib, sys
pkgs = [
  ('fastapi','__version__'),('uvicorn','__version__'),('httpx','__version__'),
  ('numpy','__version__'),('pandas','__version__'),('scikit_learn','__version__'),
]
for mod, attr in pkgs:
    try:
        m = importlib.import_module(mod)
        print(f"{mod}={getattr(m, attr)}")
    except Exception as e:
        print(f"{mod}=<missing> ({e})")
PY
echo "[Deps Smoke] Node + npm (if present):"
command -v node >/dev/null 2>&1 && node -v || echo "node not installed"
command -v npm  >/dev/null 2>&1 && npm -v  || echo "npm not installed"
echo "Done"

