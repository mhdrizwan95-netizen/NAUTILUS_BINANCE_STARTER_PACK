from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)
_METRIC_ERRORS: tuple[type[Exception], ...] = (ValueError, RuntimeError)


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOGGER.debug("%s suppressed exception: %s", context, exc, exc_info=True)


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    last_price: float = 0.0
    upl: float = 0.0
    rpl: float = 0.0
    venue: str = ""
    market: str = "spot"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "qty_base": self.quantity,
            "avg_price_quote": self.avg_price,
            "last_price_quote": self.last_price,
            "unrealized_usd": self.upl,
            "realized_usd": self.rpl,
            "venue": self.venue,
            "market": self.market,
        }


@dataclass
class PortfolioState:
    # CHANGED: Track multi-asset balances
    balances: dict[str, float] = field(default_factory=lambda: {"USDT": 0.0, "BNB": 0.0})
    cash: float = 0.0 # Derived from balances
    equity: float = 0.0
    exposure: float = 0.0
    realized: float = 0.0
    unrealized: float = 0.0
    fees: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    margin_level: float = 0.0
    margin_liability_usd: float = 0.0
    wallet_breakdown: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            "balances": self.balances,
            "cash": self.cash,
            "equity": self.equity,
            "exposure": self.exposure,
            "pnl": {
                "realized": self.realized,
                "unrealized": self.unrealized,
                "fees": self.fees,
            },
            "positions": [pos.to_dict() for pos in self.positions.values()],
            "ts": self.ts,
            "margin": {
                "level": self.margin_level,
                "liability_usd": self.margin_liability_usd,
            },
            "wallet_breakdown": dict(self.wallet_breakdown),
        }


class Portfolio:
    """Multi-Asset portfolio accounting with Binance fee logic."""

    def __init__(self, starting_balances: dict[str, float] | None = None, on_update=None) -> None:
        self._state = PortfolioState()
        if starting_balances:
            self._state.balances = starting_balances
            self._state.cash = starting_balances.get("USDT", 0.0)
            self._state.equity = self._state.cash
        self._on_update = on_update

    @property
    def state(self) -> PortfolioState:
        return self._state

    def snapshot(self) -> dict:
        return self._state.snapshot()
    
    def sync_wallet(self, balances: dict[str, float]) -> None:
        """External sync from User Data Stream."""
        self._state.balances.update(balances)
        if "USDT" in balances:
            self._state.cash = balances["USDT"]
        self._recalculate()

    def update_price(self, symbol: str, price: float) -> None:
        pos = self._state.positions.get(symbol)
        if not pos:
            return
        pos.last_price = price
        pos.upl = (price - pos.avg_price) * pos.quantity
        self._recalculate()

    def apply_fill(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee_usd: float,
        *,
        venue: str | None = None,
        market: str | None = None,
    ) -> None:
        side = side.upper()
        qty = quantity if side == "BUY" else -quantity
        
        # --- Binance Fee Logic ---
        # If we have BNB, assume fees paid in BNB (25% discount simulated)
        # Otherwise deduct from Quote (USDT)
        fee_asset = "USDT"
        if self._state.balances.get("BNB", 0) > 0.01: # Threshold
             # In a real engine we'd calculate exact BNB amount, here we simplify
             # and just decrement BNB valuation if we had price, 
             # but for USDT margined futures, fee is usually USDT.
             # Let's stick to deducting fee_usd from USDT for safety in this Starter Pack.
             pass
        
        self._state.balances["USDT"] = self._state.balances.get("USDT", 0.0) - fee_usd
        self._state.fees += fee_usd

        # Position Logic
        venue_norm = (venue or "").upper()
        market_norm = (market or ("margin" if venue_norm == "BINANCE_MARGIN" else "spot")).lower()
        if "." in symbol:
            symbol_key = symbol.upper()
        elif venue_norm:
            symbol_key = f"{symbol.upper()}.{venue_norm}"
        else:
            symbol_key = symbol.upper()
            
        position = self._state.positions.setdefault(symbol_key, Position(symbol=symbol_key))
        position.venue = venue_norm
        position.market = market_norm

        prev_qty = position.quantity
        new_qty = prev_qty + qty

        # PnL Logic
        realized = 0.0
        closing_trade = prev_qty != 0 and (prev_qty > 0 > qty or prev_qty < 0 < qty)
        
        if closing_trade:
            closed = min(abs(prev_qty), abs(qty))
            if prev_qty > 0:
                realized = (price - position.avg_price) * closed
            else:
                realized = (position.avg_price - price) * closed
            self._state.realized += realized
            position.rpl += realized
            # Add realized profit to USDT balance
            self._state.balances["USDT"] += realized

        if prev_qty == 0 or (prev_qty > 0 and qty > 0) or (prev_qty < 0 and qty < 0):
            if new_qty != 0:
                position.avg_price = (position.avg_price * abs(prev_qty) + price * abs(qty)) / abs(new_qty)
        elif math.isclose(new_qty, 0.0, abs_tol=1e-10):
            position.avg_price = 0.0
            new_qty = 0.0
        elif prev_qty > 0 > new_qty or prev_qty < 0 < new_qty:
            position.avg_price = price

        position.quantity = new_qty
        position.last_price = price
        position.upl = (position.last_price - position.avg_price) * position.quantity

        self._cleanup_positions()
        self._recalculate()
        
        if self._on_update:
            self._on_update(self._state.snapshot())

        try:
            from engine.metrics import REGISTRY as _MET
            ctr = _MET.get("orders_filled_total")
            if ctr: ctr.inc()
        except _METRIC_ERRORS:
            pass

    def _cleanup_positions(self) -> None:
        to_delete = [k for k, v in self._state.positions.items() if math.isclose(v.quantity, 0.0, abs_tol=1e-10)]
        for k in to_delete: del self._state.positions[k]

    def _recalculate(self) -> None:
        exposure = 0.0
        unrealized = 0.0
        for pos in self._state.positions.values():
            exposure += abs(pos.quantity * pos.last_price)
            unrealized += pos.upl
        
        self._state.exposure = exposure
        self._state.unrealized = unrealized
        self._state.cash = self._state.balances.get("USDT", 0.0)
        self._state.equity = self._state.cash + unrealized
        self._state.ts = time.time()
