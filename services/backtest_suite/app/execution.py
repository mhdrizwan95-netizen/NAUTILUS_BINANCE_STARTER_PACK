from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Position:
    side: str
    qty: float
    entry: float


class ExecutionModel:
    def __init__(self, fee_bp: float, slip_bp: float):
        self.fee_bp = fee_bp
        self.slip_bp = slip_bp
        self.pos: Optional[Position] = None
        self.trades = []  # list of dicts

    def _price_with_costs(self, side: str, price: float) -> float:
        slip = price * (self.slip_bp / 10000.0)
        fee = price * (self.fee_bp / 10000.0)
        if side == "buy":
            return price + slip + fee
        else:
            return price - slip - fee

    def on_signal(self, order: Dict[str, Any], bar: Dict[str, Any]):
        if order is None:
            return
        side, qty = order["side"], float(order.get("qty", 0.0))
        px = self._price_with_costs(side, bar["close"])
        if self.pos is None:
            # open
            self.pos = Position(side=side, qty=qty, entry=px)
            self.trades.append(
                {
                    "action": "open",
                    "side": side,
                    "qty": qty,
                    "price": px,
                    "notional": qty * px,
                }
            )
        else:
            # simple flip/close
            if self.pos.side != side:
                pnl = (
                    (px - self.pos.entry) * (1.0 if self.pos.side == "buy" else -1.0) * self.pos.qty
                )
                self.trades.append(
                    {
                        "action": "close",
                        "side": self.pos.side,
                        "qty": self.pos.qty,
                        "price": px,
                        "pnl": pnl,
                        "notional": self.pos.qty * px,
                    }
                )
                self.pos = None

    def mark_to_market(self, bar: Dict[str, Any]) -> float:
        if self.pos is None:
            return 0.0
        dir = 1.0 if self.pos.side == "buy" else -1.0
        return (bar["close"] - self.pos.entry) * dir * self.pos.qty
