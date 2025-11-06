# OPS Runbook

This playbook captures the day-to-day checklist for running the Nautilus HMM stack, how to control trading, and what to do when things misbehave.

## Daily Checks

| Check | Command / Location | Pass Criteria |
|-------|--------------------|---------------|
| Engine & exporter metrics | `make smoke-exporter` | `equity_usd`, `cash_usd`, `market_value_usd`, `metrics_heartbeat`, `risk_equity_buffer_usd`, `kraken_equity_usd` return non-empty values and residual ≈ 0. |
| Prometheus scrape status | `make smoke-prom` or `http://localhost:9090/targets` | `engine_binance`, `engine_kraken`, `ops`, and exporters show `health: "up"`. |
| Ops API status | `curl http://localhost:8002/status | jq` | `{"trading_enabled": true}` (or expected value) and balances populated. |
| Grafana dashboards | `http://localhost:3000` (Command Center) | Panels update, no `No data` warnings, metrics heartbeat < 60s. |
| Trend dashboards | `Trend Strategy Ops` | `trend_follow_*` counters move when signals fire, `symbol_scanner_score` shows current shortlist. |
| Executor health (if enabled) | `docker compose logs -f executor` | No repeated retry loops or venue errors. |
| Universe/Situations services | `curl http://localhost:8009/health`, `curl http://localhost:8011/health` | Return `{"ok": true}`. |
| Strategy ingest rate | `curl -G --data-urlencode 'query=rate(strategy_ticks_total{venue="binance"}[1m])' http://localhost:9090/api/v1/query | jq` | >0 for actively traded symbols; zero means mark feed stalled. |
| Tick→order latency | `curl -G --data-urlencode 'query=histogram_quantile(0.95, rate(strategy_tick_to_order_latency_ms_bucket[5m]))' http://localhost:9090/api/v1/query | jq` | <150 ms during stable periods; investigate spikes. |
| Health LEDs | `health_state`, `risk_depeg_active` in Grafana | 0=OK,1=DEGRADED,2=HALTED; alerts on sustained non‑OK. |

## Operational Controls

| Action | Command | Notes |
|--------|---------|-------|
| Pause trading | `curl -X POST http://localhost:8002/kill -H "X-Ops-Token: ${OPS_API_TOKEN}" -H "Idempotency-Key: kill-$(date +%s)" -d '{"enabled": false}'` | Sets `TRADING_ENABLED=false` in engine via governance; include `X-Ops-Actor` if you want the audit log to capture your call-sign. |
| Resume trading | Same as above with `{"enabled": true}` | Confirm by checking `/status` and `metrics_trading_enabled`. |
| Adjust strategy weights | `curl -X POST http://localhost:8002/strategy/weights -H "X-Ops-Token: ${OPS_API_TOKEN}" -H "Content-Type: application/json" -d '{"weights":{"stable_model":0.7,"canary_model":0.3}}'` | Updates `ops/strategy_weights.json`; allocator loop reflects on next tick. |
| Update HMM calibration | Edit `engine/models/hmm_calibration.json` (or `HMM_CALIBRATION_PATH`), wait 60 s or restart engine | Controls confidence gain, quote multiplier, cooldown scale; shared between backtests and live. |
| Trigger manual reconciliation | `curl -X POST http://localhost:8003/reconcile/manual` | Returns counts of fills applied; safe to run any time. |
| Inject external signal | `BODY='{"source":"test_harness","payload":{"symbol":"FOOUSDT"}}'; curl -X POST http://localhost:8003/events/external -H "Content-Type: application/json" -H "X-Events-Signature: sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$EXTERNAL_EVENTS_SECRET" -binary | xxd -p -c 256)" -d "$BODY"` | Publishes an event onto `events.external_feed`; include the signature header when `EXTERNAL_EVENTS_SECRET` is set. |
| Submit a test order | `make order ORDER_SYMBOL=BTCUSDT.BINANCE ORDER_SIDE=BUY ORDER_QUOTE=25` | Use small notional; confirm via metrics/logs. |
| Fetch portfolio snapshot | `curl http://localhost:8003/state | jq` (if exposed) or inspect `engine/state/portfolio.json` | Use for audits and recovery validation. |
| View latest orders | `tail -n 20 engine/logs/orders.jsonl | jq` | Real-time audit trail. |
| Flip feature flags | Edit `.env` and restart or export env in compose overrides | Start modules in dry-run where available; validate metrics first. |
| Force trend auto-tune reset | Delete `data/runtime/trend_auto_tune.json` and restart engine | Only do this if the state file is corrupt or you want to revert to env defaults. |
| Re-scan symbols manually | `touch data/runtime/symbol_scanner_state.json` then restart engine or call scanner control endpoint (TBD) | Scanner automatically runs every `SYMBOL_SCANNER_INTERVAL_SEC`; manual reset forces a fresh shortlist. |

### External Feed Observability

- **Command Center import**: After cloning or pulling new dashboards run `make grafana-import path=ops/observability/grafana/dashboards/command_center.json` (or import manually via Grafana UI) so the `External Feed Event Rate`, `Fetch Latency p90`, `Last Event Age`, and `Error Rate` panels appear. Verify the `feed` templating variable populates with your configured sources.
- **Prometheus alert**: Add a rule similar to:
  ```
  - alert: ExternalFeedStale
    expr: time() - external_feed_last_event_epoch{source=~".*"} > 300
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "External feed {{ $labels.source }} stale"
      description: "No events observed for {{ $labels.source }} in 5 minutes."
  ```
  Place it in `ops/observability/prometheus/rules/alerts.rules.yml` (or a dedicated file) and reload Prometheus. Tune the threshold (`300` seconds here) to match each feed’s SLA.

### Trend Auto-Tune & Symbol Scanner

- **Auto-tune status**: look for `[TREND-AUTO]` log entries or query `trend_follow_trades_total` / `trend_follow_signals_total`; each parameter change writes to `data/runtime/trend_auto_tune.json`. If you need to disable tuning quickly, set `TREND_AUTO_TUNE_ENABLED=false` in `.env` and restart `engine_binance`.
- **Symbol scanner status**: check the Grafana Trend dashboard (`symbol_scanner_score`, `symbol_scanner_selected_total`) or inspect `data/runtime/symbol_scanner_state.json` to see the active shortlist. If `SYMBOL_SCANNER_ENABLED=false`, the systematic stack falls back to the global `TRADE_SYMBOLS` allowlist.
- **Restart procedure**: after editing `.env` for either feature run `docker compose up -d engine_binance engine_binance_exporter`. The scanner starts a background thread; verify `[SCAN]` logs appear (or values change in Grafana) before trusting output.

## Restart & Recovery

1. **Graceful stop**
   ```bash
   make down        # core services
   make down-all    # include observability if needed
   ```
2. **Inspect state**
   - `engine/state/portfolio.json` — ensure last snapshot timestamp looks reasonable.
   - `data/runtime/trades.db` — optional: `sqlite3 data/runtime/trades.db '.tables'`.
   - `engine/logs/orders.jsonl` — confirm last trades prior to incident.
3. **Clean start**
   ```bash
   make up-core
   make up-obs      # optional
   ```
4. **Validate**
   - `curl http://localhost:8003/readyz`
   - `make smoke-exporter`
   - `curl http://localhost:8002/status | jq '.snapshot_loaded, .balances'`
   - Watch Grafana heartbeat panels.
5. **If state looks wrong**
   - Stop services.
   - Restore `engine/state/portfolio.json` and `data/runtime/trades.db` from backup.
   - Restart and re-run reconciliation (`/reconcile/manual`).

## Troubleshooting Guide

| Symptom | What to inspect | Remedy |
|---------|-----------------|--------|
| Orders rejected unexpectedly | `engine/logs/app.log`, `/orders` response JSON, `RiskRails` metrics (`breaker_rejections_total`, `risk_equity_floor_breach`) | Check `TRADING_ENABLED`, notional limits, exposure caps, equity floor/drawdown breakers. Adjust env or policies, or call `/kill` to reset. |
| Metrics frozen (heartbeat > 60s) | Exporter container logs (`docker compose logs engine_binance_exporter`), Prometheus targets, DNS/network | Restart exporter, ensure exporter and Prometheus share `nautilus_trading_network` (see `docs/network-dns-fix.md`). |
| Tick ingestion stalled (`strategy_ticks_total` flat) | Trader logs, Binance REST connectivity, `/health` | Ensure `VENUE=BINANCE` refresh task logs `Starting background refresh task`; restart trader if missing. |
| Latency spike (`strategy_tick_to_order_latency_ms` > 250 ms) | Host CPU, Python GC (`python_gc_*` gauges), engine logs | Reduce symbol fan-out, verify no heavy work inside `_notify_listeners`, consider scaling hardware. |
| Prometheus scrape errors | `make smoke-prom`, Prometheus UI errors | Validate targets in `ops/observability/prometheus/prometheus.yml`; ensure containers running; reload via `make prom-reload`. |
| High venue error rate / breaker tripped | `engine/logs/orders.jsonl`, `engine/logs/events.jsonl`, metrics `engine_venue_errors_total`, `venue_error_rate_pct` | Investigate root cause; reduce trading exposure; kill switch if necessary; consider raising `VENUE_ERROR_BREAKER_PCT` temporarily once resolved. |
| Executor spamming retries | `docker compose logs executor`, `ops/auto_probe.py` logs | Check engine health; throttle via env (`EXEC_INTERVAL_SEC`, `DRY_RUN=true`) or stop executor (`make executor-down`). |
| Universe / screener stale | `curl http://localhost:8009/universe | jq`, `curl http://localhost:8010/scan` | Restart affected service; watch rate-limit gauges (`screener` metrics). |
| SQLite backlog | `ls -lh data/runtime/trades.db`, `engine/storage/sqlite` queue size (enable debug logs) | Usually self-healing; if locked, restart engine to recreate connection. |

## Incident Playbooks

### Circuit breaker tripped
1. Alerts trigger when `venue_error_rate_pct` or `risk_equity_floor_breach` flips to 1.
2. Confirm via `/metrics` and engine logs; inspect `risk_equity_buffer_usd`, `risk_equity_drawdown_pct`, `venue_exposure_usd{venue="kraken"}`.
3. Pause trading (`/kill`), investigate upstream API (Binance/Kraken) or account equity changes.
4. Once stable, clear venue breaker by calling `RiskRails.record_result(True)` or restart; equity breaker auto-resets after `EQUITY_COOLDOWN_SEC` once buffer > 0.
5. Resume trading gradually (lower `MAX_NOTIONAL_USDT`, adjust strategy weights) and monitor buffer/drawdown gauges.

### Depeg detected (USDT instability)
1. Alert fires when `risk_depeg_active>0` (and Telegram health shows 🔴 HALTED with reason `depeg_trigger`).
2. Engine halts new entries; if `DEPEG_EXIT_RISK=true`, it will reduce existing positions.
3. Validate peg via `USDTUSDC` and `BTCUSDT/BTCUSDC` parity.
4. After cooldown and manual validation, re‑arm trading (engine emits health OK on daily reset or via manual helper).

### Missing server‑side stop
1. StopValidator detects missing SL (`stop_validator_missing_total`); repairs if `STOP_VALIDATOR_REPAIR=true`.
2. Telegram (shield icon) pings on repair if `STOPVAL_NOTIFY_ENABLED=true`.
3. Investigate root cause (order rejection, symbol limits); ensure protection survives reconnects.

### Funding spike (upcoming)
1. When `FUNDING_GUARD_ENABLED=true`, spikes above threshold are trimmed automatically; optional hedge with BTC.
2. Confirm trim in orders log and funding panels. Consider hedging if trims are frequent.

### Unreconciled fills detected
1. `reconcile_lag_seconds` > acceptable threshold or equities mismatch.
2. Run `curl -X POST http://localhost:8003/reconcile/manual`.
3. Inspect `engine/logs/orders.jsonl` for missing fills.
4. If still mismatch, export account snapshot manually (Binance/Kraken API) and adjust `engine/state/portfolio.json` before restart.

### Portfolio drift after restart
1. Compare `engine/state/portfolio.json` to account snapshot.
2. Check `engine/logs/orders.jsonl` for missing trades during downtime.
3. Run reconciliation and restart exporter.
4. Update snapshot manually if required; ensure `SnapshotStore.save` writes the adjusted state.

### Ops API unresponsive
1. `curl http://localhost:8002/readyz` fails.
2. Check container logs (`docker compose logs ops`).
3. Restart Ops container (`docker compose up -d --no-deps --force-recreate ops`).
4. Validate metrics (`curl http://localhost:8002/metrics`) and dashboards.

## Observability Routines

- **Validate dashboards after config changes**:
  ```bash
  make validate-obs
  ```
- **Reload Prometheus after rule updates**:
  ```bash
  make prom-reload
  ```
- **Restart Grafana to pick up new dashboards**:
  ```bash
  make grafana-restart
  ```
- **Query metrics quickly**:
  ```bash
  curl -fsS -G --data-urlencode 'query=increase(orders_submitted_total[5m])' http://localhost:9090/api/v1/query
  ```
- **Strategy latency spot check**:
  ```bash
  curl -fsS -G --data-urlencode 'query=histogram_quantile(0.5, rate(strategy_tick_to_order_latency_ms_bucket[5m]))' http://localhost:9090/api/v1/query
  ```

- **Event Breakout KPIs**: import `ops/observability/grafana/dashboards/event_breakout_kpis.json` and `slippage_heatmap.json`; keep `EVENT_BREAKOUT_METRICS=true`.

## Backups & Compliance

- Snapshot critical files daily:
  - `engine/state/portfolio.json`
  - `data/runtime/trades.db`
  - `ops/capital_allocations.json`
  - `ops/strategy_weights.json`
  - `engine/logs/orders.jsonl`
- Archive to off-host storage with timestamped tarballs.
- Rotate API keys periodically; update `.env` and restart engines after rotation.
- Review `ops/policies.yaml` after policy edits; keep a changelog for auditability.

Keep this runbook updated whenever new services are added, endpoints change, or incident responses evolve. The fastest path to calm operations is an up-to-date playbook.

## Staged Go‑Live (first 72h)

Use flags to stage risk safely (see docs/FEATURE_FLAGS.md for full list):

Hour 0–12 (observe only)
- EVENT_BREAKOUT_METRICS=true
- TELEGRAM_ENABLED=true DIGEST_INTERVAL_MIN=1440
- AUTO_CUTBACK_ENABLED=true, RISK_PARITY_ENABLED=true
- DEPEG_GUARD_ENABLED=true DEPEG_EXIT_RISK=false
- FUNDING_GUARD_ENABLED=true FUNDING_HEDGE_RATIO=0.00
- Keep EVENT_BREAKOUT_DRY_RUN=true

Hour 12–36 (small live)
- EVENT_BREAKOUT_ENABLED=true
- EVENT_BREAKOUT_DRY_RUN=false (5‑minute half‑size window)
- Keep DEX exec off; maker remains shadow unless logs prove it

Hour 36–72 (expand cautiously)
- If futures taker slippage > 8–10 bps and maker posting looks good, enable real maker for scalps (futures only)
- Flip DEPEG_EXIT_RISK=true after synthetic test; FUNDING_HEDGE_RATIO=0.30 if trims look clean
