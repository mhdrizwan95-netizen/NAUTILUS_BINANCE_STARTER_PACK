# Allocator Daemon + Deck Metrics Hook

This follow-up bundle adds:
- `ops/allocator_daemon.py` — lightweight daemon that adjusts strategy `risk_share` based on rolling PnL.
- `ops/deck_metrics.py` — helper functions to push live metrics (equity, PnL, latency, breakers) and per-strategy PnL into the Deck.
- `ops/deck_api.py` — extends the Deck API with `POST /metrics/push` and `POST /trades` for ingesting metrics and trade events.
- `deck/app.js` — shows per-strategy PnL badges alongside risk shares.
- `engine/riskrails_adapter.py` — adapter that threads `engine.dynamic_policy` helpers into existing RiskRails sizing/cap logic.
- `engine/telemetry/metrics_hook_example.py` — example publisher that streams mock metrics into the Deck.
- `ops/compose_patches/deck_depends_env.patch` + `.env.example` — lets docker-compose pick the real ops service name when it is not `hmm_ops`.

## Run the allocator
```bash
export DECK_URL=http://localhost:8002
python -m ops.allocator_daemon
```

Environment knobs:
- `REFRESH_SEC` (default 600)
- `MAX_SHARE` (default 0.55), `MIN_SHARE` (default 0.05)
- `EXPLORATION` (default 0.08)
- `EMA_ALPHA` (default 0.35)

The daemon reads `pnl_by_strategy` from Deck (`/status` or `/metrics/push`), scores each strategy (EMA + UCB-lite + exploration), normalizes weights, clips them to `[MIN_SHARE, MAX_SHARE]`, and pushes updates with `POST /allocator/weights`.

## Seed Deck metrics from the engine
```python
from ops.deck_metrics import push_metrics, push_strategy_pnl

push_metrics(
    equity_usd=equity,
    pnl_24h=pnl_24h,
    drawdown_pct=dd,
    tick_p50_ms=p50,
    tick_p95_ms=p95,
    error_rate_pct=err,
    breaker={"equity": False, "venue": False},
)
push_strategy_pnl({"scalp": pnl_scalp, "momentum": pnl_mom, "trend": pnl_trend, "event": pnl_event})
```

## Thread dynamic policy into RiskRails
```python
from engine.riskrails_adapter import LiveFeatures, compute_order

order = compute_order(
    strat_name="momentum",
    strat_type="momentum",
    base_tf="1m",
    leverage_allowed=True,
    live=LiveFeatures(
        symbol,
        price,
        atr_pct,
        spread_bps,
        depth10bps_usd,
        vol1m_usd,
        funding,
        event_heat,
        velocity,
        liq_score,
    ),
    equity_usd=equity,
    open_risk_sum_pct=sum_r,
    open_positions=n_open,
    exposure_total_usd=exposure,
    exposure_by_symbol=exposure_by_symbol,
    regime_signal=regime,
)
# order contains size_usd, stop_pct, mode, caps, etc.
```

## Tighten docker-compose dependency
Change the Deck service dependency to use an env fallback:
```yaml
depends_on:
  - ${OPS_SERVICE_NAME:-hmm_ops}
```
Then create `.env` at the repo root:
```
OPS_SERVICE_NAME=<your_ops_service>
```
This lets the Deck wait on the correct ops service, even when it is not called `hmm_ops`.
