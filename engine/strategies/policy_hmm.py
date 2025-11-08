# engine/strategies/policy_hmm.py
from __future__ import annotations

import math
import pickle  # nosec B403 - loads trusted local models only
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

from ..config import load_strategy_config
from .calibration import adjust_confidence, adjust_quote, cooldown_scale

S = load_strategy_config()

# Default directional prior used by consumers that need a quick mapping from
# discrete HMM state → directional bias.
STATE_EDGE = {0: 0.0, 1: 1.0, 2: -1.0}

# Rolling buffers per symbol
_prices: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=S.hmm_window))
_vols: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=S.hmm_window))
_last_signal_ts: Dict[str, float] = defaultdict(float)


def _vwap(prices: List[float], vols: List[float]) -> float:
    num = sum(p * v for p, v in zip(prices, vols)) or 0.0
    den = sum(vols) or 1.0
    return num / den


def _zscore(x: List[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    m = sum(x) / n
    var = sum((v - m) ** 2 for v in x) / max(1, n - 1)
    sd = math.sqrt(max(var, 1e-12))
    return (x[-1] - m) / sd


def _vola(returns: List[float]) -> float:
    # simple std of 1-min returns
    n = len(returns)
    if n < 2:
        return 0.0
    m = sum(returns) / n
    var = sum((r - m) ** 2 for r in returns) / max(1, n - 1)
    return math.sqrt(max(var, 1e-12))


def _features(sym: str) -> Optional[List[float]]:
    P, V = _prices[sym], _vols[sym]
    if len(P) < 3:  # need minimum data
        return None
    rets = [0.0] + [(P[i] - P[i - 1]) / P[i - 1] for i in range(1, len(P))]
    vwap = _vwap(list(P), list(V) if len(V) == len(P) else [1.0] * len(P))
    feats = [
        rets[-1],  # latest return
        _vola(rets[-20:]),  # short volatility
        (P[-1] - vwap) / vwap,  # dev vs VWAP
        _zscore(list(P)[-30:]),  # zscore of price
        (float(V[-1]) / max(1.0, sum(list(V)[-20:]) / 20.0) if V else 1.0),  # volume spike ratio
    ]
    return feats


def ingest_tick(sym: str, price: float, volume: float = 1.0) -> None:
    _prices[sym].append(float(price))
    _vols[sym].append(float(volume))


def _load_model():
    # Try active model link first, fall back to configured path
    active_path = Path("engine/models/active_hmm_policy.pkl")
    model_path = active_path if active_path.exists() else Path(S.hmm_model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"No HMM model found at {model_path} or {active_path}")
    print(f"[HMM] Loading model from {model_path}")
    with open(model_path, "rb") as f:
        return pickle.load(f)  # nosec B301 - models are produced by trusted pipeline


_model = None


def model():
    global _model
    if _model is None:
        _model = _load_model()
    return _model


def decide(sym: str) -> Optional[Tuple[str, float, Dict]]:
    """Return (side, quote_usdt, meta) or None if no action."""
    # cooldown
    now = time.time()
    dynamic_cooldown = max(1.0, S.cooldown_sec * cooldown_scale(sym))
    if now - _last_signal_ts[sym] < dynamic_cooldown:
        return None

    feats = _features(sym)
    if not feats:
        return None

    probs = model().predict_proba([feats])[0]  # e.g., [p_bull, p_bear, p_chop]
    base_conf = float(max(probs))
    adj_conf = adjust_confidence(sym, base_conf)
    # Map regimes → action
    p_bull, p_bear = probs[0], probs[1]
    p_chop = probs[2] if len(probs) >= 3 else 0.0
    if adj_conf < 0.5:
        return None  # low confidence

    # Get current market price for reference (used in meta, not required for decision)
    px = 0.0

    quote = adjust_quote(sym, S.quote_usdt)
    # vol-scaled sizing (example): smaller size when vola high
    # Here kept simple; robust sizing can use realized vola bins
    if p_bull > p_bear and p_bull > p_chop:
        side = "BUY"
    elif p_bear > p_bull and p_bear > p_chop:
        side = "SELL"
    else:
        return None

    _last_signal_ts[sym] = now
    meta = {
        "exp": "hmm_v1",
        "probs": probs,
        "mark": px,
        "conf": adj_conf,
        "cooldown": dynamic_cooldown,
    }
    return side, float(quote), meta
