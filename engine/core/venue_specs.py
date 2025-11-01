# engine/core/venue_specs.py
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class SymbolSpec:
    min_qty: float
    step_size: float
    min_notional: float


# Defaults as fallback if JSON loading fails
DEFAULT_SPECS = {
    "BTCUSDT": SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0),
    "ETHUSDT": SymbolSpec(min_qty=0.0001, step_size=0.0001, min_notional=5.0),
    "BNBUSDT": SymbolSpec(min_qty=0.01, step_size=0.01, min_notional=5.0),
}

DEFAULT_KRAKEN_SPECS = {
    "PI_XBTUSD": SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0),
    "PI_ETHUSD": SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0),
}

# Load from JSON if available, otherwise use defaults
SPECS_FILE = Path(__file__).parent / "venue_specs.json"
SPECS = {
    "BINANCE": {},
    "IBKR": {
        # US equities default: 1 share increments; min_notional can be set via env
        "AAPL": SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=1.0),
        "MSFT": SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=1.0),
    },
    "KRAKEN": {},
}

if SPECS_FILE.exists():
    try:
        with open(SPECS_FILE) as f:
            raw = json.load(f)
        for venue, symbols in raw.items():
            SPECS[venue] = {k: SymbolSpec(**v) for k, v in symbols.items()}
        print(
            f"Loaded venue specs from {SPECS_FILE}: {sum(len(v) for v in SPECS.values())} symbols"
        )
    except Exception as e:
        print(f"[WARN] Failed to load {SPECS_FILE}: {e}, using defaults")

# Fallback: ensure we have basic defaults if JSON is empty or failed
if not SPECS["BINANCE"]:
    SPECS["BINANCE"] = DEFAULT_SPECS.copy()
    print(f"Using default venue specs: {len(DEFAULT_SPECS)} symbols")

if "BINANCE_MARGIN" not in SPECS:
    SPECS["BINANCE_MARGIN"] = SPECS["BINANCE"]

if not SPECS["KRAKEN"]:
    SPECS["KRAKEN"] = DEFAULT_KRAKEN_SPECS.copy()

# simple fee schedule (bps)
FEES_TAKER_BPS = {
    "BINANCE": 10.0,  # 0.10% taker default; override from env if needed
    "KRAKEN": 5.0,  # 0.05% taker default for Kraken futures (override via env)
}
