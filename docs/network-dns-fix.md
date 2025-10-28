# Network / DNS Resolution Fix for Kraken Exporter

## ✅ Overview
A container networking issue prevented the `engine_kraken_exporter` service from being scraped by Prometheus — it showed as **DOWN** due to DNS failure (`lookup engine_kraken_exporter on 127.0.0.11:53: no such host`).
Once fixed, metrics flowed correctly and the Grafana dashboard began populating as expected.

---

## 🔧 Root Cause
- The Prometheus container and the `engine_kraken_exporter` container were **not** in the same Docker user-defined network, or the service DNS name didn't match the hostname used by Prometheus.
- Without a shared network with name-resolution, Prometheus couldn't resolve `engine_kraken_exporter` → failed scrapes.

---

## 🛠 Fix Applied
1. In `docker-compose.yml` and `ops/observability/docker-compose.observability.yml`, changed network config:
   ```yaml
   networks:
     nautilus_trading_network:
       driver: bridge

Ensured both services join the same nautilus_trading_network (or trading_net) bridge network.
2. Removed conflicting network alias override for engine_kraken_exporter; allowed the service name to resolve as engine_kraken_exporter.
3. Ensured that the container_name matched the service name both in compose and in Prometheus scrape config targets:.
4. Restarted containers with the corrected network settings:

docker compose down
docker compose up -d

5. Verified network membership and DNS resolution:

docker network inspect nautilus_trading_network
docker exec -it hmm_prometheus sh
ping -c 1 engine_kraken_exporter

⸻

✅ Validation Checklist
• Prometheus target for engine_kraken_exporter shows "health": "up" in /api/v1/targets.
• DNS resolves inside Prometheus container: ping engine_kraken_exporter returns IP.
• Metrics are flowing:

curl -s -G --data-urlencode 'query=equity_usd{venue="kraken"}' http://localhost:9090/api/v1/query

should return non-empty result.

• Grafana dashboard "HMM · Venue – Kraken" populates when $venue = kraken.
• Canary order submission (via engine_kraken) triggers metric change:

curl -s -G --data-urlencode 'query=increase(orders_submitted_total{venue="kraken"}[5m])' http://localhost:9090/api/v1/query

shows value > 0 after a trade.

⸻

## 🔗 Ops ↔ Engine DNS Fix (Name or service not known)

If `ops` logs show `engine poll error: [Errno -2] Name or service not known`, the Ops API container cannot resolve engine hostnames (e.g., `engine_binance`). Root cause is the `ops` service not being on the same user-defined network.

Fix:
- Ensure `ops` (and any helpers that talk to engines/extras like `situations`, `screener`, `executor`) are attached to the same network as engines.
- In `docker-compose.yml`, add:

```yaml
services:
  ops:
    networks:
      - trading_net
  engine_bybit:
    networks:
      - trading_net
  universe:
    networks:
      - trading_net
  situations:
    networks:
      - trading_net
  screener:
    networks:
      - trading_net
  executor:
    networks:
      - trading_net
  vol_ranker:
    networks:
      - trading_net
  backfill:
    networks:
      - trading_net
  slip_trainer:
    networks:
      - trading_net

networks:
  trading_net:
    external: true
    name: nautilus_trading_network
```

Then restart:

```bash
docker compose down
docker compose up -d
```

Validate from inside `ops` container:

```bash
docker compose exec ops sh -lc 'wget -qO- http://engine_binance:8003/health && echo'
```

If this returns `{"ok": true}` or similar, DNS is fixed.

⸻

🧠 Lessons for Future Venues
• Always place new services that Prometheus will scrape on the same user-defined network as Prometheus to ensure DNS name resolution works.
• Align service names/hostnames in compose, targets, and dashboard queries so there are no mismatches in labels (job, venue, instance).
• After network changes: bring down/up containers, inspect network membership, test DNS inside containers, then test metrics before dashboard relying on them.
• Document network and scrape details in repository so new team members or new venue integrations don't repeat the same issue.

⸻

📋 Commit This File

Add this file to the repo (e.g., docs/network-dns-fix.md) and include in your project's documentation section. This will serve as a reference for the next time you wire up a new venue (e.g., Bybit, IBKR) or new exporter service.

⸻

📡 Telegram DNS Sanity Check

When local DNS is flaky (e.g., curl: Could not resolve host), use the built-in helper to send a Telegram test message. It automatically falls back to an IP override if DNS resolution fails:

make telegram-ping

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your environment or in .env.
