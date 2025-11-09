#!/usr/bin/env bash
set -euo pipefail

echo "[1/4] DNS + network: ensuring compose network exists (optional)"
if command -v docker >/dev/null 2>&1; then
  docker network inspect nautilus_trading_network >/dev/null 2>&1 || docker network create nautilus_trading_network || true
fi

echo "[2/4] Curl health endpoints with timeouts"
for URL in \
  "http://localhost:8003/health" \
  "http://localhost:8002/readyz" \
  "http://localhost:8015/health" \
  ; do
  curl -fsS --max-time 2 "$URL" || echo "WARN: $URL not reachable (ok if service not running)"
done

echo "[3/4] Python httpx quick retry check"
python - <<'PY'
import httpx, time
def ping(url):
    for i in range(2):
        try:
            r = httpx.get(url, timeout=0.5)
            print(url, r.status_code)
            return
        except Exception as e:
            time.sleep(0.1*(i+1))
    print(url, 'unreachable')
for u in ["http://localhost:8003/health", "http://localhost:8002/readyz"]:
    ping(u)
PY

echo "[4/4] Verify dashboard HTTP helper resolves metrics quickly"
if [[ -f dashboard/app.py ]]; then
  rg -n "AsyncClient\(timeout=" dashboard/app.py || true
fi

echo "Network smoke finished"
