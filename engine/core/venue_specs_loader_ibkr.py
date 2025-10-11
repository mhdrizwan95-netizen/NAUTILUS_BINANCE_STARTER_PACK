#!/usr/bin/env python3
"""
IBKR Specs Auto-Loader.

Fetches minSize from IBKR contracts and updates venue_specs.json.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict
from ib_insync import IB, Stock

SPECS_PATH = Path(__file__).parent / "venue_specs.json"

@dataclass
class SymbolSpec:
    min_qty: float
    step_size: float
    min_notional: float

def fetch_ibkr_specs(symbols: list[str]) -> Dict[str, SymbolSpec]:
    ib = IB()
    ib.connect(
        host=os.getenv("IBKR_HOST","127.0.0.1"),
        port=int(os.getenv("IBKR_PORT","7497")),
        clientId=int(os.getenv("IBKR_CLIENT_ID","777")),
        readonly=True,
    )
    out = {}
    for sym in symbols:
        c = Stock(sym, "SMART", "USD")
        cds = ib.reqContractDetails(c)
        lot = 1.0
        if cds and cds[0].minSize:
            lot = float(cds[0].minSize)
        out[sym.upper()] = SymbolSpec(min_qty=lot, step_size=lot, min_notional=float(os.getenv("IBKR_MIN_NOTIONAL_USD","5")))
    ib.disconnect()
    return out

def write_specs(specs: Dict[str, SymbolSpec]):
    if SPECS_PATH.exists():
        import json
        raw = json.loads(SPECS_PATH.read_text())
    else:
        raw = {}
    raw.setdefault("IBKR", {})
    import json
    for k, v in specs.items():
        raw["IBKR"][k] = {"min_qty": v.min_qty, "step_size": v.step_size, "min_notional": v.min_notional}
    tmp = SPECS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    tmp.replace(SPECS_PATH)

if __name__ == "__main__":
    import sys
    syms = sys.argv[1:] or ["AAPL","MSFT","NVDA","TSLA"]
    write_specs(fetch_ibkr_specs(syms))
