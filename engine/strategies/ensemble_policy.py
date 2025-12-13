# engine/strategies/ensemble_policy.py
from __future__ import annotations

import time
from dataclasses import replace

from ..config import load_strategy_config
from .calibration import adjust_confidence


class _StrategyConfigProxy:
    """
    Lightweight proxy that preserves an immutable dataclass internally
    while exposing ergonomic attribute setters for tests/ops scripts.
    Assignments replace the underlying dataclass via dataclasses.replace.
    """

    __slots__ = ("_inner",)

    def __init__(self, cfg):
        object.__setattr__(self, "_inner", cfg)

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def __setattr__(self, name, value):
        if name == "_inner":
            object.__setattr__(self, name, value)
        else:
            object.__setattr__(self, "_inner", replace(self._inner, **{name: value}))

    def snapshot(self):
        """Return the current dataclass instance."""
        return self._inner


S = _StrategyConfigProxy(load_strategy_config())

_last_ts: dict[str, float] = {}


def combine(
    symbol: str,
    ma_side: str | None,
    ma_conf: float,
    hmm_decision: tuple[str, float, dict] | None,
    river_decision: dict | None = None,
) -> tuple[str, float, dict] | None:
    """
    Combine MA + HMM + River into one consensus decision.
    Returns (side, quote, meta) or None.
    """
    if not S.ensemble_enabled:
        return None

    w = S.ensemble_weights
    w_ma = w.get("ma_v1", 0.3)
    w_hmm = w.get("hmm_v1", 0.4)
    w_river = w.get("river_v1", 0.3)

    ma_val = 0 if not ma_side else (1 if ma_side == "BUY" else -1)
    hmm_val, hmm_conf = 0, 0.0
    has_hmm = hmm_decision is not None
    if has_hmm:
        hmm_val = 1 if hmm_decision[0] == "BUY" else -1
        hmm_conf = (
            max(hmm_decision[2].get("probs", [0])) if isinstance(hmm_decision[2], dict) else 0.5
        )

    # River contribution
    river_val, river_conf = 0, 0.0
    has_river = river_decision is not None and river_decision.get("prediction") is not None
    if has_river:
        river_pred = river_decision.get("prediction", 0)
        river_val = 1 if river_pred == 1 else -1  # 1=Up=BUY, 0=Down=SELL
        proba = river_decision.get("proba", {})
        river_conf = max(proba.values()) if proba else 0.5

    score = (w_ma * ma_val * ma_conf) + (w_hmm * hmm_val * hmm_conf) + (w_river * river_val * river_conf)
    conf = abs((w_ma * ma_conf) + (w_hmm * hmm_conf) + (w_river * river_conf))
    effective_conf = ma_conf if not has_hmm and not has_river else conf
    effective_conf = adjust_confidence(symbol, effective_conf)

    if effective_conf < S.ensemble_min_conf:
        return None  # no strong consensus

    side = "BUY" if score > 0 else "SELL"
    _last_ts[symbol] = time.time()

    meta = {
        "exp": "ensemble_v2",
        "score": score,
        "conf": effective_conf,
        "weights": {"ma_v1": w_ma, "hmm_v1": w_hmm, "river_v1": w_river},
        "components": {
            "ma_side": ma_side,
            "ma_conf": ma_conf,
            "hmm_side": ("BUY" if has_hmm and hmm_val > 0 else ("SELL" if has_hmm else "NONE")),
            "hmm_conf": hmm_conf,
            "river_side": ("BUY" if has_river and river_val > 0 else ("SELL" if has_river else "NONE")),
            "river_conf": river_conf,
        },
    }
    return side, S.quote_usdt, meta
