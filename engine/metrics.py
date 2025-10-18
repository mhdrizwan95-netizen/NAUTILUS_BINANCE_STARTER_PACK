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

# Per-symbol unrealized PnL (for invariants)
pnl_unrealized_symbol = Gauge("pnl_unrealized_symbol", "Unrealized PnL by symbol (USD)", ["symbol"], multiprocess_mode="max")

# Per-symbol position/basis metrics for dashboard tables
position_amt_by_symbol = Gauge("position_amt", "Position amount (signed base units)", ["symbol"], multiprocess_mode="max")
entry_price_by_symbol = Gauge("entry_price", "Average entry price (USD)", ["symbol"], multiprocess_mode="max")
unrealized_profit_by_symbol = Gauge("unrealized_profit", "Unrealized profit (USD)", ["symbol"], multiprocess_mode="max")
mark_price_by_symbol = Gauge("mark_price", "Mark price (USD)", ["symbol"], multiprocess_mode="max")

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
}

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
