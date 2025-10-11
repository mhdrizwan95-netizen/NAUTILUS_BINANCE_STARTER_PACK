#!/usr/bin/env python3
"""
Auto Lot-Size & SymbolSpec Loader.

Fetches minQty, stepSize, minNotional for all USDT pairs from Binance
and updates engine/core/venue_specs.json.
"""

import requests, json, time, logging
from pathlib import Path
from dataclasses import dataclass
from typing import Dict

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

SPECS_PATH = Path(__file__).parent / "venue_specs.json"
BINANCE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

@dataclass
class SymbolSpec:
    min_qty: float
    step_size: float
    min_notional: float

def fetch_binance_specs(quote="USDT") -> Dict[str, SymbolSpec]:
    logging.info(f"Fetching /exchangeInfo from Binance...")
    r = requests.get(BINANCE_INFO_URL, timeout=10)
    r.raise_for_status()
    data = r.json()
    specs = {}
    for s in data["symbols"]:
        if s["quoteAsset"] != quote or s["status"] != "TRADING":
            continue
        sym = s["symbol"]
        f = {f["filterType"]: f for f in s["filters"]}
        lot = f.get("LOT_SIZE", {})
        min_qty = float(lot.get("minQty", 0))
        step_size = float(lot.get("stepSize", 0))
        min_notional = float(f.get("MIN_NOTIONAL", {}).get("minNotional", 0))
        specs[sym] = SymbolSpec(min_qty, step_size, min_notional)
    logging.info(f"Fetched {len(specs)} symbols with {quote} quote.")
    return specs

def write_specs(specs: Dict[str, SymbolSpec]):
    out = {"BINANCE": {k: vars(v) for k, v in specs.items()}}
    tmp = SPECS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2))
    tmp.replace(SPECS_PATH)
    logging.info(f"Wrote {len(specs)} specs → {SPECS_PATH}")

def refresh():
    specs = fetch_binance_specs()
    write_specs(specs)

if __name__ == "__main__":
    refresh()
