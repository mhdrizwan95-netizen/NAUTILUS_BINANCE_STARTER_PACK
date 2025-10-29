from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List


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
    cash: float = 0.0
    equity: float = 0.0
    exposure: float = 0.0
    realized: float = 0.0
    unrealized: float = 0.0
    fees: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    margin_level: float = 0.0
    margin_liability_usd: float = 0.0

    def snapshot(self) -> dict:
        return {
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
        }


class Portfolio:
    """Simple FIFO portfolio accounting for spot symbols."""

    def __init__(self, starting_cash: float = 0.0) -> None:
        self._state = PortfolioState(cash=starting_cash, equity=starting_cash)

    @property
    def state(self) -> PortfolioState:
        return self._state

    # Provide snapshot method for reconciliation/persistence shims
    def snapshot(self) -> dict:
        return self._state.snapshot()

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
        venue_norm = (venue or "").upper()
        market_norm = (market or ("margin" if venue_norm == "BINANCE_MARGIN" else "spot")).lower()
        if "." in symbol:
            symbol_key = symbol.upper()
            if not venue_norm:
                venue_norm = symbol_key.split(".", 1)[1]
                if venue_norm == "BINANCE_MARGIN" and market_norm == "spot":
                    market_norm = "margin"
        elif venue_norm:
            symbol_key = f"{symbol.upper()}.{venue_norm}"
        else:
            symbol_key = symbol.upper()
        position = self._state.positions.setdefault(symbol_key, Position(symbol=symbol_key))
        if venue_norm:
            position.venue = venue_norm
        if market_norm:
            position.market = market_norm

        prev_qty = position.quantity
        new_qty = prev_qty + qty

        if side == "BUY":
            cash_change = price * quantity + fee_usd
            self._state.cash -= cash_change
            total_cost = position.avg_price * prev_qty + price * quantity
            position.quantity = new_qty
            if new_qty != 0:
                position.avg_price = total_cost / new_qty
        else:
            cash_change = price * quantity - fee_usd
            self._state.cash += cash_change
            realized = (price - position.avg_price) * quantity
            self._state.realized += realized
            position.rpl += realized
            position.quantity = new_qty
            if math.isclose(new_qty, 0.0, abs_tol=1e-10):
                position.avg_price = 0.0

        self._state.fees += fee_usd
        position.last_price = price
        position.upl = (position.last_price - position.avg_price) * position.quantity

        self._cleanup_positions()
        self._recalculate()

        # Increment filled counter for observability
        try:
            from engine.metrics import REGISTRY as _MET
            ctr = _MET.get("orders_filled_total")
            if ctr is not None:
                ctr.inc()
        except Exception:
            pass

    def _cleanup_positions(self) -> None:
        to_delete: List[str] = []
        for sym, pos in self._state.positions.items():
            if math.isclose(pos.quantity, 0.0, abs_tol=1e-10):
                pos.quantity = 0.0
                pos.avg_price = 0.0
                pos.upl = 0.0
                to_delete.append(sym)
        for sym in to_delete:
            del self._state.positions[sym]

    def _recalculate(self) -> None:
        exposure = 0.0
        unrealized = 0.0
        for pos in self._state.positions.values():
            exposure += abs(pos.quantity * pos.last_price)
            unrealized += pos.upl
        self._state.exposure = exposure
        self._state.unrealized = unrealized
        self._state.equity = self._state.cash + unrealized
        self._state.ts = time.time()
