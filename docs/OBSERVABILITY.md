# Observability

Prometheus/Grafana are provisioned under `ops/observability/`. The engine exposes rich metrics in `engine/metrics.py`.

## Key Dashboards

- Event Breakout – KPIs: `ops/observability/grafana/dashboards/event_breakout_kpis.json`
  - Open positions, DRY vs LIVE plans, trades, skips by reason, half‑size applied, trail updates, efficiency
- Execution – Slippage Heatmap: `ops/observability/grafana/dashboards/slippage_heatmap.json`
  - Heatmap by symbol using slippage skip rate; optional slippage histogram panels when `exec_slippage_bps` histogram is enabled

## Useful Metrics

- Strategy
  - `strategy_ticks_total{symbol,venue}` — confirms mark ingestion
  - `strategy_tick_to_order_latency_ms` — end‑to‑end reaction time
  - `strategy_cooldown_window_seconds{symbol,venue}` — current cooldown window
- Risk & Health
  - `venue_exposure_usd{venue}` — live exposure by venue
  - `risk_equity_buffer_usd`, `risk_equity_drawdown_pct` — equity guardrails
  - `health_state` — 0=OK,1=DEGRADED,2=HALTED
  - `risk_depeg_active` — 1 during depeg safe‑mode
- Event Breakout
  - `event_bo_plans_total{venue,symbol,dry}`
  - `event_bo_trades_total{venue,symbol}`
  - `event_bo_skips_total{reason,symbol}`
  - `event_bo_half_size_applied_total{symbol}`
  - `event_bo_trail_updates_total{symbol}`

## Quick PromQL

Median tick→order latency (5m window):
```
histogram_quantile(0.5, rate(strategy_tick_to_order_latency_ms_bucket[5m]))
```

Event Breakout plan rate (live):
```
sum(rate(event_bo_plans_total{dry="false"}[5m]))
```

Slippage flare (5m):
```
sum by (symbol)(rate(exec_slippage_bps_count[5m])) > 0
and
(sum(rate(exec_slippage_bps_sum[5m])) by (symbol)
 /
 clamp_min(sum(rate(exec_slippage_bps_count[5m])) by (symbol),1)) > 12
```

Depeg active:
```
risk_depeg_active > 0
```

## Staging Tips

- Keep `EVENT_BREAKOUT_METRICS=true` even in dry‑run for full visibility.
- Enable Telegram digest (`TELEGRAM_ENABLED=true`) for daily summaries; consider `DIGEST_6H_ENABLED=true` for 6‑hour buckets during rollout.
- Health notifications: `HEALTH_TG_ENABLED=true` to get a concise ping on state changes.
