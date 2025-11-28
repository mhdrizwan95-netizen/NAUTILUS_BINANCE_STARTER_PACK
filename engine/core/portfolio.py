from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)
_METRIC_ERRORS: tuple[type[Exception], ...] = (ValueError, RuntimeError)
from engine.config import QUOTE_CCY


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
    balances: dict[str, float] = field(default_factory=dict)  # Multi-currency: {"USDT": 1000, "BNB": 2.5}
    equity: float = 0.0
    exposure: float = 0.0
    realized: float = 0.0
    unrealized: float = 0.0
    fees: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    margin_level: float = 0.0
    margin_liability_usd: float = 0.0
    wallet_breakdown: dict[str, Any] = field(default_factory=dict)  # Deprecated, use balances

    @property
    def cash(self) -> float:
        """Backward compatibility: returns balance in quote currency (USDT)."""
        return self.balances.get(QUOTE_CCY, 0.0)

    @cash.setter
    def cash(self, value: float) -> None:
        """Backward compatibility: sets balance in quote currency."""
        self.balances[QUOTE_CCY] = value

    def snapshot(self) -> dict:
        return {
            "cash": self.cash,  # Backward compatibility
            "balances": dict(self.balances),  # New: multi-currency balances
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
    """Simple FIFO portfolio accounting for spot symbols."""

    def __init__(self, starting_cash: float = 0.0, on_update: Callable[[dict], Any] | None = None) -> None:
        # Initialize with starting cash in quote currency
        initial_balances = {QUOTE_CCY: starting_cash} if starting_cash > 0 else {}
        self._state = PortfolioState(balances=initial_balances, equity=starting_cash)
        self._on_update = on_update

    @property
    def state(self) -> PortfolioState:
        return self._state

    def get_balance(self, asset: str) -> float:
        """Get balance for a specific asset (e.g., 'USDT', 'BNB', 'FDUSD')."""
        return self._state.balances.get(asset.upper(), 0.0)

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
        else:
            cash_change = price * quantity - fee_usd
            self._state.cash += cash_change

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

        if prev_qty == 0 or (prev_qty > 0 and qty > 0) or (prev_qty < 0 and qty < 0):
            # Adding to an existing position in the same direction (or opening new)
            if new_qty != 0:
                position.avg_price = (position.avg_price * abs(prev_qty) + price * abs(qty)) / abs(
                    new_qty
                )
        elif math.isclose(new_qty, 0.0, abs_tol=1e-10):
            position.avg_price = 0.0
            new_qty = 0.0
        elif prev_qty > 0 > new_qty or prev_qty < 0 < new_qty:
            # Reversed direction – remaining portion is entered at current price
            position.avg_price = price

        position.quantity = new_qty

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
        except _METRIC_ERRORS as exc:
            _log_suppressed("portfolio.orders_filled_metric", exc)

    def _cleanup_positions(self) -> None:
        to_delete: list[str] = []
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
        if self._on_update:
            try:
                self._on_update(self._state.snapshot())
            except Exception:
                pass

    def sync_wallet(self, balances: dict[str, float]) -> None:
        """Update wallet balances from authoritative source (e.g. REST/WS)."""
        # Update balances dict
        self._state.balances = {k.upper(): v for k, v in balances.items()}
        # Also update deprecated wallet_breakdown for compatibility
        self._state.wallet_breakdown = balances.copy()
        self._recalculate()

