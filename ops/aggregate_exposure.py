# ops/aggregate_exposure.py
from __future__ import annotations
import os, math, asyncio
from typing import Dict, List, Tuple
import httpx
from dataclasses import dataclass, asdict

# Optional bridge into ibkr_prices module (if running inside same process)
try:
    from ops import ibkr_prices  # exposes PRICE cache if present
    _IBKR_PRICE_MAP = True
except Exception:
    ibkr_prices = None
    _IBKR_PRICE_MAP = False

@dataclass
class Position:
    symbol: str          # "BTCUSDT.BINANCE" | "AAPL.IBKR"
    qty_base: float
    last_price_usd: float

    @property
    def exposure_usd(self) -> float:
        return float(self.qty_base) * float(self.last_price_usd)

@dataclass
class AggregateExposure:
    by_symbol: Dict[str, Dict]   # symbol → {qty_base, last_price_usd, exposure_usd}
    totals: Dict[str, float]     # {"exposure_usd": x, "count": n, "venues": m}

def _parse_endpoints(raw: str | None) -> List[str]:
    raw = raw or "http://engine_binance:8003,http://engine_ibkr:8005"
    return [p.strip() for p in raw.split(",") if p.strip()]

def _venue_from_symbol(symbol: str) -> str:
    return symbol.split(".")[1].upper() if "." in symbol else ("BINANCE" if symbol.endswith("USDT") else "IBKR")

def _symbol_key(sym: str) -> str:
    # Normalize to "BASE.VENUE" (e.g., "BTCUSDT.BINANCE", "AAPL.IBKR")
    if "." in sym:
        base, ven = sym.split(".", 1)
        return f"{base.upper()}.{ven.upper()}"
    base = sym.upper()
    return f"{base}.BINANCE" if base.endswith("USDT") else f"{base}.IBKR"

async def _fetch_portfolio(client: httpx.AsyncClient, base_url: str) -> dict:
    try:
        r = await client.get(f"{base_url.rstrip('/')}/portfolio", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def _price_from_port_pos(p: dict) -> float | None:
    # try common fields
    for k in ("last_price_quote", "last", "mark", "price"):
        v = p.get(k)
        if isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
            return float(v)
    return None

def _maybe_fill_price_from_ibkr(symbol: str) -> float | None:
    if not _IBKR_PRICE_MAP or not ibkr_prices:
        return None
    # ibkr_prices exports Prometheus Gauges, but we also keep a small cache map if desired
    # We'll read direct from the Gauges via ._value.get()
    base = symbol.split(".")[0].upper()
    g = ibkr_prices.PRICE_METRICS.get(base)
    if g is None:
        return None
    try:
        # prometheus_client Gauge keeps value in _value.get()
        return float(g._value.get())
    except Exception:
        return None

async def aggregate_exposure(engine_endpoints_env: str | None = None,
                             include_watchlist_env: str | None = None) -> AggregateExposure:
    endpoints = _parse_endpoints(engine_endpoints_env)
    watchlist = [s.strip().upper() for s in (include_watchlist_env or os.getenv("OPS_IBKR_TICKERS", "")).split(",") if s.strip()]

    by_symbol: Dict[str, Position] = {}
    venue_set = set()

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch_portfolio(client, e) for e in endpoints], return_exceptions=True)

    for res in results:
        if not isinstance(res, dict):
            continue
        positions = res.get("positions") or []
        for p in positions:
            sym_raw = p.get("symbol") or p.get("sym") or ""
            if not sym_raw:
                continue
            sym = _symbol_key(sym_raw)
            venue_set.add(_venue_from_symbol(sym))
            qty = float(p.get("qty_base") or p.get("qty") or 0.0)
            last = _price_from_port_pos(p)

            # If IBKR and no price in engine snapshot, try bridge price
            if last is None and sym.endswith(".IBKR"):
                last = _maybe_fill_price_from_ibkr(sym) or 0.0

            pos = by_symbol.get(sym)
            if pos:
                # accumulate same symbol across venues if that ever happens (shouldn't)
                pos.qty_base += qty
                if last and not pos.last_price_usd:
                    pos.last_price_usd = float(last)
            else:
                by_symbol[sym] = Position(symbol=sym, qty_base=qty, last_price_usd=float(last or 0.0))

    # Add watchlist symbols (qty 0) so they appear in exposure heatmap with live IBKR prices
    for base in watchlist:
        sym = _symbol_key(base if "." in base else f"{base}.IBKR")
        if sym not in by_symbol:
            last = _maybe_fill_price_from_ibkr(sym) or 0.0
            by_symbol[sym] = Position(symbol=sym, qty_base=0.0, last_price_usd=float(last))

    # Build output
    out_map: Dict[str, Dict] = {}
    exposure_sum = 0.0
    count = 0
    for sym, pos in by_symbol.items():
        count += 1
        e = pos.exposure_usd if pos.last_price_usd else 0.0
        exposure_sum += e
        out_map[sym] = {
            "qty_base": float(pos.qty_base),
            "last_price_usd": float(pos.last_price_usd),
            "exposure_usd": float(e),
        }

    return AggregateExposure(
        by_symbol=out_map,
        totals={
            "exposure_usd": float(exposure_sum),
            "count": int(count),
            "venues": int(len(venue_set)) if venue_set else len(endpoints),
        },
    )
