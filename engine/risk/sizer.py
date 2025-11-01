from __future__ import annotations

from typing import Any


def atr_pct(md: Any, symbol: str, tf: str = "5m", n: int = 14) -> float:
    atr = md.atr(symbol, tf=tf, n=n) or 0.0
    px = md.last(symbol) or 0.0
    return (atr / px) if (atr > 0 and px > 0) else 0.0


def risk_parity_qty(
    per_trade_risk_usd: float, md: Any, symbol: str, tf: str, n: int
) -> float:
    px = md.last(symbol) or 0.0
    atr = md.atr(symbol, tf=tf, n=n) or 0.0
    if atr <= 0 or px <= 0:
        return 0.0
    return float(per_trade_risk_usd) / float(atr)


def clamp_notional(qty: float, px: float, min_usd: float, max_usd: float) -> float:
    if px <= 0:
        return qty
    notional = qty * px
    if notional < min_usd:
        return min_usd / px
    if notional > max_usd:
        return max_usd / px
    return qty
