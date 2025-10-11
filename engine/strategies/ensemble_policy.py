# engine/strategies/ensemble_policy.py
from __future__ import annotations
import math, time
from typing import Dict, Optional, Tuple, List
from ..config import load_strategy_config

S = load_strategy_config()

_last_ts: Dict[str, float] = {}

def combine(symbol: str, ma_side: Optional[str], ma_conf: float,
            hmm_decision: Optional[Tuple[str, float, Dict]]) -> Optional[Tuple[str, float, Dict]]:
    """
    Combine MA + HMM into one consensus decision.
    Returns (side, quote, meta) or None.
    """
    if not S.ensemble_enabled:
        return None

    w = S.ensemble_weights
    w_ma = w.get("ma_v1", 0.5)
    w_hmm = w.get("hmm_v1", 0.5)

    ma_val = 0 if not ma_side else (1 if ma_side == "BUY" else -1)
    hmm_val, hmm_conf = 0, 0.0
    if hmm_decision:
        hmm_val = 1 if hmm_decision[0] == "BUY" else -1
        hmm_conf = max(hmm_decision[2].get("probs", [0])) if isinstance(hmm_decision[2], dict) else 0.5

    score = (w_ma * ma_val * ma_conf) + (w_hmm * hmm_val * hmm_conf)
    conf = abs((w_ma * ma_conf) + (w_hmm * hmm_conf))

    if abs(score) < S.ensemble_min_conf:
        return None  # no strong consensus

    side = "BUY" if score > 0 else "SELL"
    _last_ts[symbol] = time.time()

    meta = {
        "exp": "ensemble_v1",
        "score": score,
        "conf": conf,
        "weights": {"ma_v1": w_ma, "hmm_v1": w_hmm},
        "components": {
            "ma_side": ma_side,
            "ma_conf": ma_conf,
            "hmm_side": "BUY" if hmm_val > 0 else "SELL",
            "hmm_conf": hmm_conf,
        },
    }
    return side, S.quote_usdt, meta
