# backtests/fills.py
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class FillParams:
    base_slip_bps: float = 0.5  # baseline slip at calm times
    vol_sensitivity: float = 0.35  # add slip per vol-z
    spread_weight: float = 0.50  # fraction of spread paid/received
    depth_impact: float = 0.10  # extra slip if qty > top depth
    min_slip_bp: float = 0.05
    max_slip_bp: float = 8.0


class InvalidMidError(ValueError):
    def __init__(self) -> None:
        super().__init__("Bad mid for fill")


def realized_vol_bp(mid_history: list[float], window: int = 120) -> float:
    """Realized vol in bp over `window` deltas (simple)."""
    n = min(len(mid_history), window)
    if n < 2:
        return 0.0
    mids = mid_history[-n:]
    rets = [(mids[i] / mids[i - 1] - 1.0) for i in range(1, len(mids)) if mids[i - 1] > 0]
    if not rets:
        return 0.0
    # approx bp sigma per tick
    import statistics as stats

    return abs(stats.stdev(rets)) * 1e4


def slip_bp(side: str, spread_bp: float, vol_bp: float, depth_ratio: float, p: FillParams) -> float:
    # volatility z-score proxy (cap to sane range)
    vol_z = (vol_bp - 5.0) / max(1.0, 5.0)  # assume ~5bp typical per-tick sigma
    slip = p.base_slip_bps + p.vol_sensitivity * max(0.0, vol_z)
    slip += p.spread_weight * max(0.0, spread_bp) * 0.5  # pay ~half spread impact
    slip += p.depth_impact * max(0.0, depth_ratio - 1.0)  # if taking > L1 depth
    return float(min(max(slip, p.min_slip_bp), p.max_slip_bp))


def fill_price(
    side: str,
    mid: float,
    bid: float | None,
    ask: float | None,
    spread_bp: float,
    vol_bp: float,
    qty: float,
    l1_depth: float | None,
    mid_history: list[float],
    params: FillParams | None = None,
) -> float:
    params = params or FillParams()
    if not math.isfinite(mid) or mid <= 0:
        raise InvalidMidError()
    # depth_ratio: how much of top-of-book you consume (1.0 == all L1)
    depth_ratio = float(qty / max(l1_depth or qty, 1e-12))
    sbp = slip_bp(side, spread_bp, vol_bp, depth_ratio, params)
    slip_px = (sbp / 1e4) * mid
    if side == "BUY":
        base = ask if ask and ask > 0 else mid
        return float(base + slip_px)
    else:
        base = bid if bid and bid > 0 else mid
        return float(base - slip_px)
