# Observability Dashboards

This directory contains Prometheus + Grafana configs and production dashboards for the HMM trading system.

Dashboards (provisioned)
- HMM • Venue – Binance: `ops/observability/grafana/dashboards/venue_binance.json` (uid: `hmm-venue-binance`)
- HMM • Venue – IBKR: `ops/observability/grafana/dashboards/venue_ibkr.json` (uid: `hmm-venue-ibkr`)
- HMM • Command Center (All Venues): `ops/observability/grafana/dashboards/command_center.json` (uid: `hmm-command-center`)

Conventions
- Datasource UID: `prometheus`
- Refresh: `5s`
- Default time range: `now-6h` to `now`
- All venue dashboards scope metrics with exact job filters (no regex): `{job="engine_binance"}` or `{job="engine_ibkr"}`.
- All deltas/rates use `clamp_min(..., 0)` to avoid negative samples after restarts.

How to run
1) Start Prometheus + Grafana (observability stack):
   - `docker compose -f ops/observability/docker-compose.observability.yml up -d`
2) Access Grafana: http://localhost:3000 (admin/admin by default in compose)
3) Dashboards auto-provision under folder "HMM" via `ops/observability/grafana/provisioning/dashboards/dashboards.yml`.

Verification (manual)
- Prometheus reachability:
  - `curl -fsS http://localhost:9090/api/v1/label/job/values | jq '.data'`
- Metric sanity per venue:
  - `curl -fsS 'http://localhost:9090/api/v1/query?query=equity_usd{job="engine_binance"}' | jq '.data.result'`
  - `curl -fsS 'http://localhost:9090/api/v1/query?query=equity_usd{job="engine_ibkr"}' | jq '.data.result'`
- No negative deltas:
  - `curl -fsS 'http://localhost:9090/api/v1/query?query=clamp_min(sum(increase(orders_filled_total{job="engine_binance"}[15m])),0)' | jq '.data.result'`
- Grafana datasource UID check:
  - `curl -fsS http://localhost:3000/api/datasources | jq '.[] | {uid:.uid, name:.name, type:.type}'`
- Dashboard import check:
  - `curl -fsS 'http://localhost:3000/api/search?query=HMM%20%E2%80%A2%20Venue%20%E2%80%93%20Binance' | jq .`
  - `curl -fsS 'http://localhost:3000/api/search?query=HMM%20%E2%80%A2%20Venue%20%E2%80%93%20IBKR' | jq .`
  - `curl -fsS 'http://localhost:3000/api/search?query=HMM%20%E2%80%A2%20Command%20Center' | jq .`

What each dashboard shows
- Venue – Binance: Futures-focused view with equity/cash/UPNL, open positions table, per-symbol UPNL, order flow and latency, rails (breaker, error rate, reconcile lag), and a simple screener context.
- Venue – IBKR: Spot/equity semantics with equity/cash/market value, per-symbol positions, (optional) commission and FX impact if exposed, order flow/latency, and rails.
- Command Center: Multi-venue rollups (equity, UPNL, realized PnL), uptime, global breaker, repeated venue cards, and risk/health views by venue.

Common gotchas
- Counter resets after restarts can cause negative deltas; all panels use `clamp_min` to avoid this, but very short windows can still look noisy.
- If a metric isn’t exported by a venue (e.g., `ibkr_commission_usd_total`), the corresponding panel will be empty.
- Ensure each engine exports with the correct `job` label: `engine_binance`, `engine_ibkr`.
