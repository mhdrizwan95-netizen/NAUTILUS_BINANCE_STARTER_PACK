"""
Dynamic Universe Scorer: compute per-symbol Opportunity Score.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SymbolFeatures:
    symbol: str
    quote_volume_1m_usd: float
    book_depth_usd: float
    spread_bps: float
    velocity: float
    atr_pct: float
    funding_rate_8h: float = 0.0
    event_heat: float = 0.0


def _z(x, mean, std):
    return 0.0 if std <= 1e-9 else (x - mean) / std


def score_symbols(features: List[SymbolFeatures]) -> Dict[str, float]:
    if not features:
        return {}
    vols = [f.quote_volume_1m_usd for f in features]
    depths = [f.book_depth_usd for f in features]
    spreads = [f.spread_bps for f in features]
    atrs = [f.atr_pct for f in features]
    mvol = sum(vols) / len(vols)
    s_vol = (sum((v - mvol) ** 2 for v in vols) / max(1, len(vols) - 1)) ** 0.5
    mdep = sum(depths) / len(depths)
    s_dep = (sum((d - mdep) ** 2 for d in depths) / max(1, len(depths) - 1)) ** 0.5
    mspr = sum(spreads) / len(spreads)
    s_spr = (sum((s - mspr) ** 2 for s in spreads) / max(1, len(spreads) - 1)) ** 0.5
    matr = sum(atrs) / len(atrs)
    s_atr = (sum((a - matr) ** 2 for a in atrs) / max(1, len(atrs) - 1)) ** 0.5

    scores = {}
    for f in features:
        liq = 0.5 * _z(f.quote_volume_1m_usd, mvol, s_vol) + 0.5 * _z(
            f.book_depth_usd, mdep, s_dep
        )
        vol = _z(f.atr_pct, matr, s_atr)
        spr = -_z(f.spread_bps, mspr, s_spr)
        mom = f.velocity * 2.0
        fund = 0.5 if f.funding_rate_8h > 0 else 0.0
        evt = f.event_heat * 2.0
        score = (
            0.25 * liq + 0.20 * vol + 0.25 * mom + 0.10 * spr + 0.05 * fund + 0.15 * evt
        )
        scores[f.symbol] = float(score)
    return scores
