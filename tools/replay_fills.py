#!/usr/bin/env python3
"""
Deterministic replay harness for fills/trades JSON fixture.

Usage:
  python tools/replay_fills.py tests/fixtures/fills_btcusdt.json

Input file format (JSON list):
[
  {"symbol": "BTCUSDT.BINANCE", "side": "BUY",  "qty": 0.001, "price": 50000.0, "fee_usd": 0.05},
  {"symbol": "BTCUSDT.BINANCE", "side": "SELL", "qty": 0.001, "price": 50500.0, "fee_usd": 0.05}
]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from engine.core.portfolio import Portfolio


def main(path: str) -> int:
    fp = Path(path)
    data = json.loads(fp.read_text())
    p = Portfolio()
    for fill in data:
        p.apply_fill(
            symbol=str(fill["symbol"]).upper(),
            side=str(fill["side"]).upper(),
            quantity=float(fill["qty"]),
            price=float(fill["price"]),
            fee_usd=float(fill.get("fee_usd", 0.0)),
        )
    snap = p.state.snapshot()
    print(
        json.dumps(
            {
                "cash": snap["cash"],
                "equity": snap["equity"],
                "exposure": snap["exposure"],
                "pnl": snap["pnl"],
                "positions": snap["positions"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/replay_fills.py <path-to-fills.json>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
