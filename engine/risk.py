from __future__ import annotations
import time, threading, collections
from collections import deque, defaultdict
from typing import Deque, Dict, Literal
from .config import RiskConfig, load_risk_config
from .metrics import breaker_rejections, venue_error_rate_pct, breaker_state

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
        self.events: Deque[float] = deque()

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

    def check_order(
        self,
        *,
        symbol: str,
        side: Side,
        quote: float | None,
        quantity: float | None,
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

        # Trading toggle
        if not self.cfg.trading_enabled:
            return False, {
                "error": "TRADING_DISABLED",
                "message": "Trading is disabled by configuration.",
                "hint": "Set TRADING_ENABLED=true to enable."
            }

        # Symbol allowlist (USDT universe)
        if self.cfg.trade_symbols is not None:
            symbol_base = symbol.split(".")[0].upper()
            allowed_bases = {s.split(".")[0].upper() for s in self.cfg.trade_symbols}
            if symbol_base not in allowed_bases:
                return False, {
                    "error": "SYMBOL_NOT_ALLOWED",
                    "message": f"{symbol} is not enabled.",
                    "allowed": [f"{s}.BINANCE" for s in sorted(self.cfg.trade_symbols)],
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
        try:
            snap = order_router.portfolio_snapshot()
            prices = order_router.exchange_client().get_last_price
        except Exception:
            snap, prices = ({}, lambda _: None)
        symbol_base = symbol.split(".")[0]
        last = prices(f"{symbol_base}.BINANCE") or 0
        qty = float(quantity) if quantity else 0.0
        quote_amt = float(quote) if quote else 0.0
        # approximate resulting exposure change in USD
        delta_usd = quote_amt if quote_amt else qty * float(last or 0)
        total_expo = float(snap.get("equity_usd", 0)) - float(snap.get("cash_usd", 0))
        # sum symbol exposure
        sym_expo = 0.0
        for p in (snap.get("positions") or []):
            if p.get("symbol","").split(".")[0] == symbol_base:
                sym_expo += float(p.get("qty_base",0)) * float(p.get("last_price_quote") or last or 0)
        sym_after = abs(sym_expo + delta_usd)
        total_after = abs(total_expo + delta_usd)
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

        # Rate limiting
        if not self.ratelimiter.allow():
            return False, {
                "error": "ORDER_RATE_EXCEEDED",
                "message": f"Max {self.cfg.max_orders_per_min}/min exceeded.",
                "window_sec": 60,
            }

        return True, {}

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

    def check_breaker(self):
        """Check if circuit breaker is tripped."""
        if self._breaker_tripped:
            raise RiskError("VENUE_BREAKER_OPEN", "Venue error-rate breaker is open; strategy paused.")
