import os
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry
from prometheus_client import multiprocess
from fastapi import APIRouter, Response

router = APIRouter()

orders_submitted = Counter("orders_submitted_total", "Orders accepted by engine")
orders_rejected = Counter("orders_rejected_total", "Orders rejected by validation")
orders_filled = Counter("orders_filled_total", "Orders that reached FILLED state")
venue_trades = Counter("venue_trades_total", "Trades fetched from venue (applied via reconciliation)")
orders_canceled = Counter("orders_canceled_total", "Orders canceled by venue or user")
orders_expired = Counter("orders_expired_total", "Orders that expired at venue")
breaker_rejections = Counter("breaker_rejections_total", "Orders rejected by breakers")
venue_errors = Counter(
    "engine_venue_errors_total",
    "Venue error events grouped by venue and error code",
    ["venue", "error"],
)
# Aggregated per-process as max to avoid double-counting under multiprocess
venue_error_rate_pct = Gauge("venue_error_rate_pct", "Venue error pct (rolling window)", multiprocess_mode="max")
breaker_state = Gauge("breaker_state", "1 if breaker open, else 0", multiprocess_mode="max")
orders_rounded = Counter("orders_rounded_total", "Orders that required qty rounding")
fees_paid_total = Gauge("fees_paid_total", "Total fees paid in USD")

fill_latency = Histogram("fill_latency_ms", "Order fill latency (ms)", buckets=(10, 50, 100, 250, 500, 1000, 2500))
pnl_realized = Gauge("pnl_realized_total", "Realized profit/loss in USDT", multiprocess_mode="max")
pnl_unrealized = Gauge("pnl_unrealized_total", "Unrealized profit/loss in USDT", multiprocess_mode="max")
equity_usd = Gauge("equity_usd", "Total account equity", multiprocess_mode="max")
cash_usd = Gauge("cash_usd", "Free cash in USD", multiprocess_mode="max")
exposure_usd = Gauge("exposure_usd", "Open exposure in USD", multiprocess_mode="max")
market_value_usd = Gauge("market_value_usd", "Signed market value of open positions in USD", multiprocess_mode="max")
initial_margin_usd = Gauge("initial_margin_usd", "Initial margin currently in use (USD)", multiprocess_mode="max")
maint_margin_usd = Gauge("maint_margin_usd", "Maintenance margin requirement (USD)", multiprocess_mode="max")
available_usd = Gauge("available_usd", "Available balance to trade/withdraw (USD)", multiprocess_mode="max")
snapshot_id = Gauge("snapshot_id", "Sequential snapshot counter for exporter loop", multiprocess_mode="max")
max_notional_usdt = Gauge("max_notional_usdt", "Current MAX_NOTIONAL_USDT limit", multiprocess_mode="max")
trading_enabled_gauge = Gauge("trading_enabled", "1 if trading enabled, else 0", multiprocess_mode="max")
snapshot_loaded_gauge = Gauge("snapshot_loaded", "1 if a portfolio snapshot is loaded, else 0", multiprocess_mode="max")
mark_time_epoch = Gauge("mark_time_epoch", "Unix time when positions were last marked to market", multiprocess_mode="max")
health_state = Gauge("health_state", "0=OK,1=DEGRADED,2=HALTED", multiprocess_mode="max")
try:
    from prometheus_client import Counter as _Counter
    health_transitions_total = _Counter("health_transitions_total", "Health FSM transitions", ["from", "to", "reason"])  # type: ignore
    REGISTRY["health_transitions_total"] = health_transitions_total
except Exception:
    pass

MARK_PRICE = Gauge("mark_price_usd", "Live mark price", ["symbol","venue"])
mark_price_freshness_sec = Gauge(
    "mark_price_freshness_sec",
    "Seconds since last observed mark price",
    ["symbol", "venue"],
    multiprocess_mode="max",
)

# Position and entry price tracking
POSITION_SIZE = Gauge("position_size", "Contracts held", ["symbol","venue","role"])
ENTRY_PRICE_USD = Gauge("entry_price_usd", "Avg entry price", ["symbol","venue","role"])
UPNL_USD = Gauge("upnl_usd", "Unrealized PnL (USD)", ["symbol","venue","role"])

# Per-symbol unrealized PnL (for invariants)
pnl_unrealized_symbol = Gauge("pnl_unrealized_symbol", "Unrealized PnL by symbol (USD)", ["symbol"], multiprocess_mode="max")

# Per-symbol position/basis metrics for dashboard tables
position_amt_by_symbol = Gauge("position_amt", "Position amount (signed base units)", ["symbol"], multiprocess_mode="max")
entry_price_by_symbol = Gauge("entry_price", "Average entry price (USD)", ["symbol"], multiprocess_mode="max")
unrealized_profit_by_symbol = Gauge("unrealized_profit", "Unrealized profit (USD)", ["symbol"], multiprocess_mode="max")
mark_price_by_symbol = Gauge("mark_price", "Mark price (USD)", ["symbol"], multiprocess_mode="max")

# NOTE: Metrics declared here are shared across workers; ensure PROMETHEUS_MULTIPROC_DIR is set when running multiprocess exports.

# Venue/risk telemetry
venue_exposure_usd = Gauge("venue_exposure_usd", "Aggregate exposure per venue (USD)", ["venue"], multiprocess_mode="max")
risk_equity_buffer_usd = Gauge("risk_equity_buffer_usd", "Equity buffer above configured floor (USD)", multiprocess_mode="max")
risk_equity_drawdown_pct = Gauge("risk_equity_drawdown_pct", "Peak-to-trough equity drawdown percent", multiprocess_mode="max")
risk_equity_floor_breach = Gauge("risk_equity_floor_breach", "1 if equity breaker currently tripped", multiprocess_mode="max")
exposure_cap_usd = Gauge("exposure_cap_usd", "Configured exposure cap per venue (USD)", ["venue"], multiprocess_mode="max")
risk_equity_floor_usd = Gauge("risk_equity_floor_usd", "Configured equity floor (USD)", multiprocess_mode="max")
risk_equity_drawdown_limit_pct = Gauge("risk_equity_drawdown_limit_pct", "Configured equity drawdown breaker percent", multiprocess_mode="max")
risk_metrics_freshness_sec = Gauge("risk_metrics_freshness_sec", "Seconds since last risk telemetry refresh", multiprocess_mode="max")
risk_exposure_headroom_usd = Gauge("risk_exposure_headroom_usd", "Remaining venue exposure capacity (USD)", ["venue"], multiprocess_mode="max")

# Kraken telemetry
kraken_equity_usd = Gauge("kraken_equity_usd", "Kraken account equity from telemetry loop", multiprocess_mode="max")
kraken_unrealized_usd = Gauge("kraken_unrealized_usd", "Kraken unrealized PnL from telemetry loop", multiprocess_mode="max")
kraken_equity_drawdown_pct = Gauge("kraken_equity_drawdown_pct", "Kraken equity drawdown percent", multiprocess_mode="max")

# Strategy loop observability
strategy_signal = Gauge(
    "strategy_signal",
    "Signed strategy signal (-1 sell, 0 flat, 1 buy)",
    ["symbol", "venue"],
    multiprocess_mode="livesum",
)
strategy_confidence = Gauge(
    "strategy_confidence",
    "Strategy decision confidence (0-1)",
    ["symbol", "venue"],
    multiprocess_mode="livesum",
)
strategy_orders_total = Counter(
    "strategy_orders_total",
    "Orders generated by automated strategy",
    ["symbol", "venue", "side", "source"],
)
strategy_ticks_total = Counter(
    "strategy_ticks_total",
    "Price ticks delivered to strategy loop",
    ["symbol", "venue"],
)
strategy_tick_to_order_latency_ms = Histogram(
    "strategy_tick_to_order_latency_ms",
    "Latency from mark ingestion to order submission (ms)",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)
strategy_cooldown_window_seconds = Gauge(
    "strategy_cooldown_window_seconds",
    "Dynamic cooldown window applied before re-entry",
    ["symbol", "venue"],
    multiprocess_mode="max",
)

# Metrics self-check heartbeat
metrics_heartbeat = Gauge("metrics_heartbeat", "Timestamp of last metrics system update", multiprocess_mode="max")

# Production polish metrics
reconcile_lag_seconds = Gauge("reconcile_lag_seconds", "Seconds since last portfolio reconcile")
ws_disconnects_total = Counter("ws_disconnects_total", "Websocket disconnects observed")
last_specs_refresh_epoch = Gauge("last_specs_refresh_epoch", "Unix time of last venue specs refresh")
submit_to_ack_ms = Histogram(
    "submit_to_ack_ms",
    "Latency from order submit to venue ack (ms)",
    buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)

# Registry for access from other modules
REGISTRY = {
    "orders_submitted_total": orders_submitted,
    "orders_rejected_total": orders_rejected,
    "orders_filled_total": orders_filled,
    "venue_trades_total": venue_trades,
    "orders_canceled_total": orders_canceled,
    "orders_expired_total": orders_expired,
    "breaker_rejections_total": breaker_rejections,
    "engine_venue_errors_total": venue_errors,
    "venue_error_rate_pct": venue_error_rate_pct,
    "breaker_state": breaker_state,
    "fees_paid_total": fees_paid_total,
    "orders_rounded_total": orders_rounded,
    "metrics_heartbeat": metrics_heartbeat,
    "reconcile_lag_seconds": reconcile_lag_seconds,
    "ws_disconnects_total": ws_disconnects_total,
    "last_specs_refresh_epoch": last_specs_refresh_epoch,
    "submit_to_ack_ms": submit_to_ack_ms,
    "fill_latency_ms": fill_latency,
    "pnl_realized_total": pnl_realized,
    "pnl_unrealized_total": pnl_unrealized,
    "equity_usd": equity_usd,
    "cash_usd": cash_usd,
    "exposure_usd": exposure_usd,
    "market_value_usd": market_value_usd,
    "initial_margin_usd": initial_margin_usd,
    "maint_margin_usd": maint_margin_usd,
    "available_usd": available_usd,
    "snapshot_id": snapshot_id,
    "max_notional_usdt": max_notional_usdt,
    "trading_enabled": trading_enabled_gauge,
    "snapshot_loaded": snapshot_loaded_gauge,
    "mark_time_epoch": mark_time_epoch,
    "pnl_unrealized_symbol": pnl_unrealized_symbol,
    "position_amt": position_amt_by_symbol,
    "entry_price": entry_price_by_symbol,
    "unrealized_profit": unrealized_profit_by_symbol,
    "mark_price": mark_price_by_symbol,
    "mark_price_freshness_sec": mark_price_freshness_sec,
    "strategy_signal": strategy_signal,
    "strategy_confidence": strategy_confidence,
    "strategy_orders_total": strategy_orders_total,
    "strategy_ticks_total": strategy_ticks_total,
    "strategy_tick_to_order_latency_ms": strategy_tick_to_order_latency_ms,
    "strategy_cooldown_window_seconds": strategy_cooldown_window_seconds,
    "venue_exposure_usd": venue_exposure_usd,
    "risk_equity_buffer_usd": risk_equity_buffer_usd,
    "risk_equity_drawdown_pct": risk_equity_drawdown_pct,
    "risk_equity_floor_breach": risk_equity_floor_breach,
    "exposure_cap_usd": exposure_cap_usd,
    "risk_equity_floor_usd": risk_equity_floor_usd,
    "risk_equity_drawdown_limit_pct": risk_equity_drawdown_limit_pct,
    "risk_metrics_freshness_sec": risk_metrics_freshness_sec,
    "risk_exposure_headroom_usd": risk_exposure_headroom_usd,
    "kraken_equity_usd": kraken_equity_usd,
    "kraken_unrealized_usd": kraken_unrealized_usd,
    "kraken_equity_drawdown_pct": kraken_equity_drawdown_pct,
}

# ---- Event Breakout metrics (feature-gated via env) ----
try:
    from prometheus_client import Counter, Gauge as _Gauge
    event_bo_plans_total = Counter("event_bo_plans_total", "Event BO plans", ["venue", "symbol", "dry"])  # type: ignore
    event_bo_trades_total = Counter("event_bo_trades_total", "Event BO trades", ["venue", "symbol"])  # type: ignore
    event_bo_skips_total = Counter("event_bo_skips_total", "Event BO skips", ["reason", "symbol"])  # type: ignore
    event_bo_half_size_applied_total = Counter("event_bo_half_size_applied_total", "Half-size applied", ["symbol"])  # type: ignore
    event_bo_trail_updates_total = Counter("event_bo_trail_updates_total", "Trailing stop amends", ["symbol"])  # type: ignore
    event_bo_trail_exits_total = Counter("event_bo_trail_exits_total", "Trailing exits (position closed)", ["symbol"])  # type: ignore
    event_bo_open_positions = _Gauge("event_bo_open_positions", "Open EVENT positions")  # type: ignore
    REGISTRY.update({
        "event_bo_plans_total": event_bo_plans_total,
        "event_bo_trades_total": event_bo_trades_total,
        "event_bo_skips_total": event_bo_skips_total,
        "event_bo_half_size_applied_total": event_bo_half_size_applied_total,
        "event_bo_trail_updates_total": event_bo_trail_updates_total,
        "event_bo_trail_exits_total": event_bo_trail_exits_total,
        "event_bo_open_positions": event_bo_open_positions,
    })
except Exception:
    # Metrics export may be disabled in some contexts
    pass

# Optional execution slippage histogram (symbol, venue, intent)
try:
    exec_slippage_bps = Histogram(
        "exec_slippage_bps",
        "Per-trade slippage in bps",
        ["symbol", "venue", "intent"],
        buckets=(1, 2, 3, 5, 8, 10, 15, 20, 30, 50, 80, 100)
    )
    REGISTRY["exec_slippage_bps"] = exec_slippage_bps
except Exception:
    pass

# Guards telemetry
try:
    risk_depeg_triggers_total = Counter("risk_depeg_triggers_total", "Depeg guard triggers")
    risk_depeg_active = Gauge("risk_depeg_active", "1 if depeg safe-mode active else 0")
    funding_spike_events_total = Counter("funding_spike_events_total", "Funding spike events", ["symbol"])  # type: ignore
    REGISTRY.update({
        "risk_depeg_triggers_total": risk_depeg_triggers_total,
        "risk_depeg_active": risk_depeg_active,
        "funding_spike_events_total": funding_spike_events_total,
    })
except Exception:
    pass

try:
    stop_validator_missing_total = Counter("stop_validator_missing_total", "Missing protection detected", ["symbol", "kind"])  # type: ignore
    stop_validator_repaired_total = Counter("stop_validator_repaired_total", "Repairs performed", ["symbol", "kind"])  # type: ignore
    REGISTRY.update({
        "stop_validator_missing_total": stop_validator_missing_total,
        "stop_validator_repaired_total": stop_validator_repaired_total,
    })
except Exception:
    pass
try:
    stop_validator_alerts_total = Counter("stop_validator_alerts_total", "StopValidator telegram alerts", ["symbol", "kind"])  # type: ignore
    REGISTRY["stop_validator_alerts_total"] = stop_validator_alerts_total
except Exception:
    pass

_CORE_ENABLED = os.getenv("METRICS_DISABLE_CORE", "").lower() not in {"1", "true", "yes"}

_CORE_METRICS = {
    "equity_usd",
    "cash_usd",
    "market_value_usd",
    "initial_margin_usd",
    "maint_margin_usd",
    "available_usd",
    "mark_time_epoch",
    "snapshot_id",
    "metrics_heartbeat",
}

_CORE_SYMBOL_METRICS = {
    "position_amt",
    "entry_price",
    "unrealized_profit",
    "mark_price",
}


def update_portfolio_gauges(cash: float, realized: float, unrealized: float, exposure: float) -> None:
    """Update portfolio state gauges."""
    if not _CORE_ENABLED:
        return
    cash_usd.set(cash)
    pnl_realized.set(realized)
    pnl_unrealized.set(unrealized)
    exposure_usd.set(exposure)
    equity_usd.set(cash + unrealized)


def core_metrics_enabled() -> bool:
    return _CORE_ENABLED


def set_core_metric(name: str, value: float) -> None:
    if not _CORE_ENABLED:
        return
    gauge = REGISTRY.get(name)
    if gauge is None:
        return
    try:
        gauge.set(float(value))
    except Exception:
        pass


def set_core_symbol_metric(name: str, *, symbol: str, value: float) -> None:
    if not _CORE_ENABLED:
        return
    gauge = REGISTRY.get(name)
    if gauge is None:
        return
    try:
        gauge.labels(symbol=symbol).set(float(value))
        if name == "mark_price":
            venue = os.getenv("VENUE", "BINANCE").lower()
            try:
                MARK_PRICE.labels(symbol=symbol, venue=venue).set(float(value))
            except Exception:
                pass
    except Exception:
        pass


def reset_core_metrics() -> None:
    if not _CORE_ENABLED:
        return
    for key in _CORE_METRICS:
        gauge = REGISTRY.get(key)
        if gauge is None:
            continue
        try:
            gauge.set(0.0)
        except Exception:
            pass
    for key in _CORE_SYMBOL_METRICS:
        gauge = REGISTRY.get(key)
        if gauge is None:
            continue
        try:
            gauge.clear()
        except Exception:
            pass


def set_trading_enabled(enabled: bool) -> None:
    """Set trading enabled gauge."""
    trading_enabled_gauge.set(1 if enabled else 0)


def set_max_notional(value: float) -> None:
    """Set max notional gauge."""
    try:
        max_notional_usdt.set(float(value))
    except Exception:
        pass


@router.get("/metrics")
def get_metrics():
    """Expose Prometheus metrics (multiprocess-safe)."""
    mp_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    use_multiproc = False
    if mp_dir:
        path = Path(mp_dir)
        try:
            use_multiproc = path.exists() and any(path.iterdir())
        except Exception:
            use_multiproc = False

    if use_multiproc:
        try:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            payload = generate_latest(registry)
        except Exception:
            payload = generate_latest()
    else:
        payload = generate_latest()
    return Response(payload, media_type=CONTENT_TYPE_LATEST)
