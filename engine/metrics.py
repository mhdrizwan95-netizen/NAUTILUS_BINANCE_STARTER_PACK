from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter, Response

router = APIRouter()

orders_submitted = Counter("orders_submitted_total", "Orders accepted by engine")
orders_rejected = Counter("orders_rejected_total", "Orders rejected by validation")
orders_filled = Counter("orders_filled_total", "Orders that reached FILLED state")
orders_canceled = Counter("orders_canceled_total", "Orders canceled by venue or user")
orders_expired = Counter("orders_expired_total", "Orders that expired at venue")
breaker_rejections = Counter("breaker_rejections_total", "Orders rejected by breakers")
venue_error_rate_pct = Gauge("venue_error_rate_pct", "Venue error pct (rolling window)")
breaker_state = Gauge("breaker_state", "1 if breaker open, else 0")
orders_rounded = Counter("orders_rounded_total", "Orders that required qty rounding")
fees_paid_total = Gauge("fees_paid_total", "Total fees paid in USD")

fill_latency = Histogram("fill_latency_ms", "Order fill latency (ms)", buckets=(10, 50, 100, 250, 500, 1000, 2500))
pnl_realized = Gauge("pnl_realized_total", "Realized profit/loss in USDT")
pnl_unrealized = Gauge("pnl_unrealized_total", "Unrealized profit/loss in USDT")
equity_usd = Gauge("equity_usd", "Total account equity")
cash_usd = Gauge("cash_usd", "Free cash in USD")
exposure_usd = Gauge("exposure_usd", "Open exposure in USD")
max_notional_usdt = Gauge("max_notional_usdt", "Current MAX_NOTIONAL_USDT limit")
trading_enabled_gauge = Gauge("trading_enabled", "1 if trading enabled, else 0")

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
    "orders_canceled_total": orders_canceled,
    "orders_expired_total": orders_expired,
    "breaker_rejections_total": breaker_rejections,
    "venue_error_rate_pct": venue_error_rate_pct,
    "breaker_state": breaker_state,
    "fees_paid_total": fees_paid_total,
    "orders_rounded_total": orders_rounded,
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
    "max_notional_usdt": max_notional_usdt,
    "trading_enabled": trading_enabled_gauge,
}


def update_portfolio_gauges(cash: float, realized: float, unrealized: float, exposure: float) -> None:
    """Update portfolio state gauges."""
    cash_usd.set(cash)
    pnl_realized.set(realized)
    pnl_unrealized.set(unrealized)
    exposure_usd.set(exposure)
    equity_usd.set(cash + unrealized)


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
    """Expose Prometheus metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
