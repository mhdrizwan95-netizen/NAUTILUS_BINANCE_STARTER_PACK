from __future__ import annotations

import collections
import logging
import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any, Literal

from .config import RiskConfig
from .core.market_resolver import resolve_market_choice
from .metrics import (
    breaker_rejections,
    breaker_state,
    exposure_cap_usd,
    risk_equity_buffer_usd,
    risk_equity_drawdown_limit_pct,
    risk_equity_drawdown_pct,
    risk_equity_floor_breach,
    risk_equity_floor_usd,
    risk_exposure_headroom_usd,
    venue_error_rate_pct,
    venue_exposure_usd,
)

logger = logging.getLogger(__name__)

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


class RiskError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


Side = Literal["BUY", "SELL"]


class OrderRateLimiter:
    """
    Per-minute sliding window rate limiter across all symbols.
    """

    def __init__(self, max_per_min: int):
        self.max_per_min = max_per_min
        self.events: deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        cutoff = now - 60.0
        while self.events and self.events[0] < cutoff:
            self.events.popleft()
        if len(self.events) >= self.max_per_min:
            return False
        self.events.append(now)
        return True


class RiskRails:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.ratelimiter = OrderRateLimiter(cfg.max_orders_per_min)
        self._err_lock = threading.Lock()
        self._err_window = collections.deque()  # (ts, ok_bool)
        self._breaker_tripped = False
        self._equity_peak = 0.0
        self._equity_breaker_active = False
        self._equity_breaker_until = 0.0
        self._last_equity = 0.0

    def check_order(
        self,
        *,
        symbol: str,
        side: Side,
        quote: float | None,
        quantity: float | None,
        market: str | None = None,
    ) -> tuple[bool, dict]:
        """
        Validate an order request. Returns (ok, error_json).
        Only one of `quote` (notional USDT) or `quantity` (base) must be provided.
        """
        from .core import order_router

        # Breaker check first
        try:
            self.check_breaker()
        except RiskError as e:
            breaker_rejections.inc()
            return False, {"error": e.code, "message": str(e)}

        # Trading toggle (single source of truth: flag file overrides config)
        if _trading_disabled_via_flag():
            return False, {
                "error": "TRADING_DISABLED",
                "message": "Trading disabled by daily stop or operator flag.",
                "hint": "Remove or set state/trading_enabled.flag=true to re-enable at boundary.",
            }
        if not self.cfg.trading_enabled:
            return False, {
                "error": "TRADING_DISABLED",
                "message": "Trading is disabled by configuration.",
                "hint": "Set TRADING_ENABLED=true to enable.",
            }

        # Symbol allowlist (USDT universe)
        if self.cfg.trade_symbols:
            symbol_base = symbol.split(".")[0].upper()
            allowed_bases = {s.split(".")[0].upper() for s in self.cfg.trade_symbols}
            if symbol_base not in allowed_bases:
                return False, {
                    "error": "SYMBOL_NOT_ALLOWED",
                    "message": f"{symbol} is not enabled.",
                    "allowed": [f"{s}.BINANCE" for s in sorted(self.cfg.trade_symbols)],
                }

        # Symbol quarantine (soft gate): two recent stops -> temporary block
        try:
            from . import risk_quarantine as _rq  # lazy import to avoid cycles

            q, remain = _rq.is_quarantined(symbol)
        except (ImportError, _SUPPRESSIBLE_EXCEPTIONS) as exc:
            _log_suppressed("risk quarantine lookup", exc)
            q, remain = (False, 0.0)
        if q:
            return False, {
                "error": "SYMBOL_QUARANTINED",
                "message": f"{symbol} is temporarily quarantined for {remain:.0f}s due to repeated stops.",
                "cooldown_sec": remain,
            }

        # Exactly one of quote or quantity
        if (quote is None and quantity is None) or (quote is not None and quantity is not None):
            return False, {
                "error": "ORDER_SHAPE_INVALID",
                "message": "Specify exactly one of {'quote','quantity'}.",
            }

        # Notional rails
        notional = float(quote) if quote is not None else None
        if notional is not None:
            if notional < self.cfg.min_notional_usdt:
                return False, {
                    "error": "NOTIONAL_TOO_SMALL",
                    "message": f"Notional {notional:.2f} < MIN_NOTIONAL_USDT {self.cfg.min_notional_usdt:.2f}",
                    "min_notional_usdt": self.cfg.min_notional_usdt,
                }
            if notional > self.cfg.max_notional_usdt:
                return False, {
                    "error": "NOTIONAL_TOO_LARGE",
                    "message": f"Notional {notional:.2f} > MAX_NOTIONAL_USDT {self.cfg.max_notional_usdt:.2f}",
                    "max_notional_usdt": self.cfg.max_notional_usdt,
                }

        # Exposure breakers (symbol & total)
        snap: dict[str, Any] = {}
        portfolio_state: Any = None
        prices: Callable[[str], float]

        def _zero_price(_: str) -> float:
            return 0.0

        try:
            router_mod = order_router
            snap_fn = getattr(router_mod, "portfolio_snapshot", None)
            raw_snap = snap_fn() if callable(snap_fn) else {}
            if isinstance(raw_snap, dict):
                snap = raw_snap
            svc_fn = getattr(router_mod, "portfolio_service", None)
            if callable(svc_fn):
                portfolio = svc_fn()
                portfolio_state = getattr(portfolio, "state", None)

            client = None
            exch_fn = getattr(router_mod, "exchange_client", None)
            if callable(exch_fn):
                client = exch_fn()
            get_price = getattr(client, "get_last_price", None) if client is not None else None

            if callable(get_price):

                def _price_lookup(sym: str) -> float:
                    try:
                        res = get_price(sym)
                        if hasattr(res, "__await__"):
                            return 0.0
                        if isinstance(res, (int, float)):
                            return float(res)
                        return float(res)  # type: ignore[arg-type]
                    except _SUPPRESSIBLE_EXCEPTIONS as exc:
                        _log_suppressed("risk price lookup", exc)
                        return 0.0

                prices = _price_lookup
            else:
                prices = _zero_price
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("risk snapshot fetch", exc)
            snap = {}
            prices = _zero_price

        symbol_base = symbol.split(".")[0]
        venue = symbol.split(".")[1].upper() if "." in symbol else "BINANCE"
        requested_market = (market or "").lower() if isinstance(market, str) else None
        resolved_market = resolve_market_choice(symbol, default="spot")
        if requested_market:
            resolved_market = requested_market

        if resolved_market == "margin" and not self.cfg.margin_enabled:
            return False, {
                "error": "MARGIN_DISABLED",
                "message": "Margin trading disabled by configuration.",
                "hint": "Set MARGIN_ENABLED=true to allow margin orders.",
            }
        if resolved_market == "options" and not self.cfg.options_enabled:
            return False, {
                "error": "OPTIONS_DISABLED",
                "message": "Options trading disabled by configuration.",
                "hint": "Set OPTIONS_ENABLED=true to allow options orders.",
            }

        def _resolve_price(sym: str) -> float:
            try:
                px = prices(sym)
                if hasattr(px, "__await__"):
                    # Cannot await in sync context; fall back to 0
                    return 0.0
                return float(px or 0.0)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("risk resolve price", exc)
                return 0.0

        base_symbol = symbol_base if symbol_base.endswith("USD") else f"{symbol_base}USD"
        primary_lookup = symbol if "." in symbol else f"{symbol_base}.BINANCE"
        last_price = _resolve_price(primary_lookup)
        if last_price == 0.0:
            last_price = _resolve_price(base_symbol)

        qty = float(quantity) if quantity else 0.0
        quote_amt = float(quote) if quote else 0.0
        if quote_amt <= 0 and qty > 0 and last_price <= 0:
            breaker_rejections.inc()
            return False, {
                "error": "PRICE_UNAVAILABLE",
                "message": f"Unable to price {symbol} for risk checks; retry when market data is available.",
            }
        side_mult = 1.0 if side.upper() == "BUY" else -1.0
        delta_signed = side_mult * (quote_amt if quote_amt else qty * float(last_price or 0.0))

        raw_positions = snap.get("positions") if isinstance(snap, dict) else None
        positions = list(raw_positions) if isinstance(raw_positions, (list, tuple)) else []
        sym_expo = 0.0
        total_expo = 0.0
        venue_exposures: dict[str, float] = defaultdict(float)

        for pos in positions:
            try:
                if not isinstance(pos, dict):
                    continue
                pos_symbol_raw = pos.get("symbol") or ""
                pos_symbol = pos_symbol_raw.upper()
                if not pos_symbol:
                    continue
                pos_base = pos_symbol.split(".")[0]
                pos_venue = pos_symbol.split(".")[1].upper() if "." in pos_symbol else "BINANCE"
                qty_base = float(pos.get("qty_base", 0.0) or 0.0)
                mark_px = pos.get("last_price_quote")
                if not mark_px:
                    if "." in pos_symbol:
                        mark_px = _resolve_price(pos_symbol)
                    else:
                        mark_px = _resolve_price(f"{pos_base}.BINANCE")
                value = qty_base * float(mark_px or 0.0)
                venue_exposures[pos_venue] += value
                total_expo += value
                if pos_base == symbol_base:
                    sym_expo += value
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("risk position ingestion", exc)
                continue

        # Update exposure gauges
        self._update_exposure_gauges(venue_exposures)

        sym_after = abs(sym_expo + delta_signed)
        total_after = abs(total_expo + delta_signed)
        venue_after = abs(venue_exposures.get(venue, 0.0) + delta_signed)
        if sym_after > self.cfg.exposure_cap_symbol_usd:
            breaker_rejections.inc()
            return False, {
                "error": "EXPOSURE_SYMBOL_CAP",
                "message": f"Exposure cap per symbol exceeded: {sym_after:.2f} > {self.cfg.exposure_cap_symbol_usd}",
            }
        if total_after > self.cfg.exposure_cap_total_usd:
            breaker_rejections.inc()
            return False, {
                "error": "EXPOSURE_TOTAL_CAP",
                "message": f"Total exposure cap exceeded: {total_after:.2f} > {self.cfg.exposure_cap_total_usd}",
            }
        if venue_after > self.cfg.exposure_cap_venue_usd:
            breaker_rejections.inc()
            return False, {
                "error": "EXPOSURE_VENUE_CAP",
                "message": f"Venue exposure cap exceeded for {venue}: {venue_after:.2f} > {self.cfg.exposure_cap_venue_usd}",
            }

        if resolved_market == "margin" and self.cfg.margin_enabled:
            margin_level_val = self._sanitize_float(getattr(portfolio_state, "margin_level", None))
            if (
                margin_level_val is not None
                and margin_level_val > 0
                and margin_level_val < self.cfg.margin_min_level
            ):
                return False, {
                    "error": "MARGIN_LEVEL_LOW",
                    "message": f"Margin level {margin_level_val:.2f} below configured floor {self.cfg.margin_min_level:.2f}",
                }
            margin_liability_val = self._sanitize_float(
                getattr(portfolio_state, "margin_liability_usd", None)
            )
            if (
                self.cfg.margin_max_liability_usd > 0
                and margin_liability_val is not None
                and margin_liability_val > self.cfg.margin_max_liability_usd
            ):
                return False, {
                    "error": "MARGIN_LIABILITY_LIMIT",
                    "message": f"Cross-margin liability {margin_liability_val:.2f} exceeds limit {self.cfg.margin_max_liability_usd:.2f}",
                }
            equity_val = self._sanitize_float(getattr(portfolio_state, "equity", None)) or 0.0
            max_leverage = max(self.cfg.margin_max_leverage, 0.0)
            if max_leverage > 0 and equity_val > 0:
                current_abs_expo = abs(sym_expo)
                projected_abs_expo = abs(sym_expo + delta_signed)
                increment_notional = max(projected_abs_expo - current_abs_expo, 0.0)
                current_liability = max(margin_liability_val or 0.0, 0.0)
                projected_liability = current_liability + increment_notional
                effective_leverage = projected_liability / max(equity_val, 1e-9)
                if effective_leverage > max_leverage:
                    return False, {
                        "error": "MARGIN_LEVERAGE_LIMIT",
                        "message": (
                            f"Projected margin leverage {effective_leverage:.2f}x exceeds limit {max_leverage:.2f}x"
                        ),
                    }

        metrics_state = self.refresh_snapshot_metrics(snap)
        if metrics_state.breaker_active:
            breaker_rejections.inc()
            return False, metrics_state.breaker_payload

        # Rate limiting
        if not self.ratelimiter.allow():
            return False, {
                "error": "ORDER_RATE_EXCEEDED",
                "message": f"Max {self.cfg.max_orders_per_min}/min exceeded.",
                "window_sec": 60,
            }

        return True, {}

    class SnapshotMetricsState:
        __slots__ = ("breaker_active", "breaker_payload")

        def __init__(
            self, breaker_active: bool, breaker_payload: dict[str, Any] | None = None
        ) -> None:
            self.breaker_active = breaker_active
            self.breaker_payload = breaker_payload or {}

    def refresh_snapshot_metrics(
        self, snap: dict[str, Any] | None, venue: str | None = None
    ) -> RiskRails.SnapshotMetricsState:
        """Refresh risk gauges from a portfolio snapshot.

        Snapshot contract (best-effort):
        - `equity_usd` (float) or fallback `equity`
        - `cash_usd` / `cash` and `pnl.unrealized` for derived equity
        - `positions`: list of dicts containing `symbol`, `qty_base`, `last_price_quote`
        - `ts` (seconds) or `ts_ms` (milliseconds) timestamps for freshness tracking
        Additional keys are ignored. Example payload::

            {
                "ts": 1_700_000_000,
                "equity_usd": 10_500.0,
                "pnl": {"unrealized": 120.0},
                "positions": [
                    {
                        "symbol": "PI_XBTUSD.KRAKEN",
                        "qty_base": 0.5,
                        "last_price_quote": 42_000.0
                    }
                ]
            }
        """
        venue_key = venue.lower() if venue else None
        self._update_exposures_from_snapshot(snap, venue_key)

        equity_raw = self._extract_equity(snap)
        equity = self._sanitize_float(equity_raw)
        now = time.time()
        breaker_payload: dict[str, Any] | None = None
        breaker_active = False

        self._set_config_gauges(venue_key)

        if equity is not None:
            self._last_equity = equity
            if self._equity_peak <= 0.0 or equity > self._equity_peak:
                self._equity_peak = equity

            drawdown_pct = self._compute_drawdown_pct(equity)
            buffer_usd = max(0.0, equity - self.cfg.equity_floor_usd)
            floor_breach = equity < self.cfg.equity_floor_usd
            drawdown_breach = drawdown_pct >= self.cfg.equity_drawdown_limit_pct

            try:
                risk_equity_buffer_usd.set(buffer_usd)
                risk_equity_drawdown_pct.set(drawdown_pct)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("risk equity gauges", exc)

            if floor_breach or drawdown_breach:
                breaker_active = True
                self._equity_breaker_active = True
                self._equity_breaker_until = max(
                    self._equity_breaker_until, now + self.cfg.equity_cooldown_sec
                )
                try:
                    risk_equity_floor_breach.set(1)
                except _SUPPRESSIBLE_EXCEPTIONS as exc:
                    _log_suppressed("risk floor breach set", exc)
                remaining = self._equity_breaker_until - now
                breaker_payload = {
                    "error": "EQUITY_FLOOR" if floor_breach else "EQUITY_DRAWDOWN",
                    "message": f"Equity breaker active ({remaining:.0f}s cooldown)",
                    "cooldown_sec": max(0.0, remaining),
                }
            else:
                if self._equity_breaker_active and now >= self._equity_breaker_until:
                    self._equity_breaker_active = False
                if not self._equity_breaker_active:
                    try:
                        risk_equity_floor_breach.set(0)
                    except _SUPPRESSIBLE_EXCEPTIONS as exc:
                        _log_suppressed("risk floor reset (equity)", exc)
        else:
            if self._equity_breaker_active and now >= self._equity_breaker_until:
                self._equity_breaker_active = False
            if not self._equity_breaker_active:
                try:
                    risk_equity_floor_breach.set(0)
                except _SUPPRESSIBLE_EXCEPTIONS as exc:
                    _log_suppressed("risk floor reset (no equity)", exc)

        return RiskRails.SnapshotMetricsState(
            breaker_active=breaker_active, breaker_payload=breaker_payload
        )

    def _extract_equity(self, snap: dict[str, Any] | None) -> float | None:
        snap_dict = snap if isinstance(snap, dict) else None
        if snap_dict is None:
            return None
        try:
            for key in ("equity_usd", "equity"):
                val = snap_dict.get(key)
                if val is not None:
                    return float(val)
            cash = self._sanitize_float(snap_dict.get("cash_usd"))
            if cash is None:
                cash = self._sanitize_float(snap_dict.get("cash"))
            pnl_candidate = snap_dict.get("pnl")
            pnl_section = pnl_candidate if isinstance(pnl_candidate, dict) else {}
            unrealized = self._sanitize_float(pnl_section.get("unrealized"))
            if cash is not None or unrealized is not None:
                return (cash or 0.0) + (unrealized or 0.0)
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("risk extract equity", exc)
            return None
        return None

    def _compute_drawdown_pct(self, equity: float) -> float:
        peak = self._equity_peak
        if peak <= 0.0:
            return 0.0
        dd = max((peak - equity) / peak * 100.0, 0.0)
        if not math.isfinite(dd) or dd < 0.0:
            return 0.0
        return dd

    def _sanitize_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            val = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(val):
            return None
        return val

    def _update_exposure_gauges(self, venue_exposures: dict[str, float]) -> None:
        try:
            cap = max(0.0, float(self.cfg.exposure_cap_venue_usd))
            for ven, val in venue_exposures.items():
                safe_val = abs(val) if math.isfinite(val) else 0.0
                venue_exposure_usd.labels(venue=ven).set(max(0.0, safe_val))
                headroom = max(0.0, cap - safe_val)
                risk_exposure_headroom_usd.labels(venue=ven).set(headroom)
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("risk exposure gauges", exc)

    def _update_exposures_from_snapshot(
        self, snap: dict[str, Any] | None, venue_default: str | None
    ) -> None:
        if not isinstance(snap, dict):
            if venue_default is not None:
                self._update_exposure_gauges({venue_default: 0.0})
            return

        positions = snap.get("positions") if isinstance(snap, dict) else None
        if not isinstance(positions, list):
            if venue_default is not None:
                self._update_exposure_gauges({venue_default: 0.0})
            return

        exposures: dict[str, float] = defaultdict(float)
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            symbol_raw = pos.get("symbol")
            if not isinstance(symbol_raw, str) or not symbol_raw:
                continue
            parts = symbol_raw.split(".")
            parts[0]
            pos_venue = (parts[1] if len(parts) > 1 else venue_default or "binance").lower()
            qty = self._sanitize_float(pos.get("qty_base")) or 0.0
            last_px = self._sanitize_float(pos.get("last_price_quote"))
            if last_px is None:
                last_px = 0.0
            value = qty * last_px
            exposures[pos_venue] += value

        if venue_default is not None and venue_default not in exposures:
            exposures[venue_default] = 0.0

        if exposures:
            self._update_exposure_gauges(exposures)

    def _set_config_gauges(self, venue_key: str | None) -> None:
        try:
            risk_equity_floor_usd.set(self.cfg.equity_floor_usd)
            risk_equity_drawdown_limit_pct.set(self.cfg.equity_drawdown_limit_pct)
            if venue_key is not None:
                cap = max(0.0, float(self.cfg.exposure_cap_venue_usd))
                exposure_cap_usd.labels(venue=venue_key).set(cap)
                risk_exposure_headroom_usd.labels(venue=venue_key).set(cap)
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("risk config gauges", exc)

    def record_result(self, ok: bool):
        """Record venue operation result for error rate monitoring."""
        now = time.time()
        with self._err_lock:
            self._err_window.append((now, ok))
            cutoff = now - self.cfg.venue_error_window_sec
            while self._err_window and self._err_window[0][0] < cutoff:
                self._err_window.popleft()
            if self._err_window:
                errs = sum(1 for _, o in self._err_window if not o)
                rate = 100.0 * errs / len(self._err_window)
                self._breaker_tripped = rate >= self.cfg.venue_error_breaker_pct
                venue_error_rate_pct.set(rate)
                breaker_state.set(1 if self._breaker_tripped else 0)

    def current_error_rate_pct(self) -> float:
        """Return the rolling venue error rate percentage."""
        with self._err_lock:
            if not self._err_window:
                return 0.0
            errs = sum(1 for _, ok in self._err_window if not ok)
            return float(100.0 * errs / len(self._err_window))

    def venue_breaker_open(self) -> bool:
        """True if the venue error-rate breaker is tripped."""
        return bool(self._breaker_tripped)

    def equity_breaker_open(self) -> bool:
        """True if the equity breaker is currently enforced."""
        if not self._equity_breaker_active:
            return False
        now = time.time()
        return now < self._equity_breaker_until

    def current_drawdown_pct(self) -> float:
        """Return the latest computed equity drawdown percentage."""
        if self._last_equity <= 0.0:
            return 0.0
        try:
            return max(0.0, float(self._compute_drawdown_pct(self._last_equity)))
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("risk drawdown calc", exc)
            return 0.0

    def last_equity(self) -> float:
        """Return the last observed equity value (best effort)."""
        return float(self._last_equity or 0.0)

    def check_breaker(self):
        """Check if circuit breaker is tripped."""
        if self._breaker_tripped:
            raise RiskError(
                "VENUE_BREAKER_OPEN",
                "Venue error-rate breaker is open; strategy paused.",
            )
        if self._equity_breaker_active:
            now = time.time()
            if now < self._equity_breaker_until:
                remaining = self._equity_breaker_until - now
                raise RiskError(
                    "EQUITY_BREAKER_OPEN",
                    f"Equity breaker cooling down ({remaining:.0f}s remaining)",
                )
            # Cooldown expired but equity breaker still flagged; reset.
            self._equity_breaker_active = False
            try:
                risk_equity_floor_breach.set(0)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("risk breaker reset", exc)


def _trading_disabled_via_flag() -> bool:
    try:
        import os

        path = "state/trading_enabled.flag"
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as fh:
            raw = (fh.read() or "").strip().lower()
    except (OSError, ValueError):
        return False
    return raw in {"0", "false", "no", "off"}
