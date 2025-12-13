# engine/strategies/policy_hmm.py
from __future__ import annotations

import logging
import math
import os
import pickle  # nosec B403 - loads trusted local models only
import time
from collections import defaultdict, deque
from pathlib import Path

from ..config import load_strategy_config
from ..services.param_client import get_cached_params, update_param_features
from .calibration import adjust_confidence, adjust_quote, cooldown_scale
from engine.strategies.vol_target import VolatilityManager

S = load_strategy_config()
PARAM_STRATEGY = "hmm"

# Default directional prior used by consumers that need a quick mapping from
# discrete HMM state → directional bias.
STATE_EDGE = {0: 0.0, 1: 1.0, 2: -1.0}

# Rolling buffers per symbol
_prices: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=S.hmm_window))
_vols: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=S.hmm_window))
_last_signal_ts: dict[str, float] = defaultdict(float)
_vol_managers: dict[str, VolatilityManager] = defaultdict(lambda: VolatilityManager(target_vol_ann=0.40)) # 40% Target Vol


class HMMModelNotFoundError(FileNotFoundError):
    """Raised when the trained HMM policy file is missing."""

    def __init__(self, model_path: Path, active_path: Path) -> None:
        super().__init__(f"No HMM model found at {model_path} or {active_path}")


def _vwap(prices: list[float], vols: list[float]) -> float:
    num = sum(p * v for p, v in zip(prices, vols, strict=False)) or 0.0
    den = sum(vols) or 1.0
    return num / den


def _zscore(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    m = sum(x) / n
    var = sum((v - m) ** 2 for v in x) / max(1, n - 1)
    sd = math.sqrt(max(var, 1e-12))
    return (x[-1] - m) / sd


def _vola(returns: list[float]) -> float:
    # simple std of 1-min returns
    n = len(returns)
    if n < 2:
        return 0.0
    m = sum(returns) / n
    var = sum((r - m) ** 2 for r in returns) / max(1, n - 1)
    return math.sqrt(max(var, 1e-12))


def _features(sym: str) -> list[float] | None:
    P, V = _prices[sym], _vols[sym]
    if len(P) < 3:  # need minimum data
        logging.warning(f"[HMM] {sym}: Not enough data for features ({len(P)} < 3)")
        return None
    # Feature 1: Log Returns
    # Handle zeros to avoid math domain error
    rets = [0.0]
    for i in range(1, len(P)):
        p_curr, p_prev = P[i], P[i-1]
        try:
            r = math.log(p_curr / p_prev)
        except (ValueError, ZeroDivisionError):
            r = 0.0
        rets.append(r)

    # Feature 2: Institutional Volatility (EMA)
    # Use the live manager's current estimate (fast access)
    inst_vol = _vol_managers[sym].get_annualized_vol()
    
    # Check if manager is "warmed up" (has basic data), else fallback to simple std
    if inst_vol == 0.0:
       inst_vol = _vola(rets[-20:]) * math.sqrt(525600) # Ann approx

    vwap = _vwap(list(P), list(V) if len(V) == len(P) else [1.0] * len(P))
    
    feats = [
        rets[-1],  # latest log return
        inst_vol,  # Annualized EMA Volatility
        (P[-1] - vwap) / vwap,  # dev vs VWAP
        _zscore(list(P)[-30:]),  # zscore of price
        (float(V[-1]) / max(1.0, sum(list(V)[-20:]) / 20.0) if V else 1.0),  # volume spike ratio
    ]
    logging.info(f"[HMM] {sym}: Computed features: {feats}")
    return feats


def _feature_payload(feats: list[float]) -> dict[str, float]:
    return {
        "ret": float(feats[0]),
        "vol": float(feats[1]),
        "dev_vwap": float(feats[2]),
        "zscore": float(feats[3]),
        "vol_spike": float(feats[4]),
    }


def ingest_tick(sym: str, price: float, volume: float = 1.0) -> None:
    # print(f"[HMM] Ingesting {sym}: {price}")
    _prices[sym].append(float(price))
    _vols[sym].append(float(volume))
    _vol_managers[sym].update(float(price))


def _load_model():
    # Try active model link first, fall back to configured path
    active_path = Path("engine/models/active_hmm_policy.pkl")
    model_path = active_path if active_path.exists() else Path(S.hmm_model_path)
    if not model_path.exists():
        raise HMMModelNotFoundError(model_path, active_path)
    print(f"[HMM] Loading model from {model_path}")
    with open(model_path, "rb") as f:
        data = pickle.load(f)  # nosec B301
        print(f"[HMM] Loaded data type: {type(data)}")
        if isinstance(data, dict):
            print(f"[HMM] Data keys: {list(data.keys())}")
            if "model" in data:
                print("[HMM] Loaded model packet (dict). Extracting model object.")
                mdl = data["model"]
                print(f"[HMM] Extracted model type: {type(mdl)}")
                return mdl
        return data


_model = None


def model():
    global _model
    if _model is None:
        _model = _load_model()
    return _model


def reload_model(event: dict | None = None) -> None:
    """Clear the cached model to force a reload on next access."""
    global _model
    print(f"[HMM] Reloading model due to event: {event}")
    _model = None


def get_regime(sym: str) -> dict | None:
    """Return HMM regime info (probs, confidence) without trading logic."""
    feats = _features(sym)
    if not feats:
        return None
    try:
        probs = model().predict_proba([feats])[0]
    except Exception as exc:
        return None

    base_conf = float(max(probs))
    adj_conf = adjust_confidence(sym, base_conf)
    p_bull, p_bear = probs[0], probs[1]
    p_chop = probs[2] if len(probs) >= 3 else 0.0

    regime = "CHOP"
    if p_bull > p_bear and p_bull > p_chop:
        regime = "BULL"
    elif p_bear > p_bull and p_bear > p_chop:
        regime = "BEAR"

    return {
        "regime": regime,
        "conf": adj_conf,
        "probs": probs.tolist(),
        "p_bull": p_bull,
        "p_bear": p_bear,
        "p_chop": p_chop,
        "features": _feature_payload(feats),
    }


def decide(sym: str) -> tuple[str, float, dict] | None:
    """Return (side, quote_usdt, meta) or None if no action."""
    now = time.time()
    instrument = sym.split(".")[0].upper()
    feats = _features(sym)
    if not feats:
        # logging.debug(f"[HMM] {sym}: Not enough features yet (len={len(_prices[sym])})")
        return None
    feature_payload = _feature_payload(feats)
    update_param_features(PARAM_STRATEGY, instrument, feature_payload)
    selection = get_cached_params(PARAM_STRATEGY, instrument) or {}
    params = selection.get("params", {})
    cooldown_setting = float(params.get("cooldown_sec") or S.cooldown_sec)
    dynamic_cooldown = max(1.0, cooldown_setting * cooldown_scale(sym))
    if now - _last_signal_ts[sym] < dynamic_cooldown:
        logging.info(f"[HMM] {sym}: Cooldown active ({now - _last_signal_ts[sym]:.1f} < {dynamic_cooldown:.1f})")
        return None

    probs = model().predict_proba([feats])[0]  # e.g., [p_bull, p_bear, p_chop]
    base_conf = float(max(probs))
    adj_conf = adjust_confidence(sym, base_conf)
    # Map regimes → action
    p_bull, p_bear = probs[0], probs[1]
    p_chop = probs[2] if len(probs) >= 3 else 0.0
    
    min_conf = float(os.getenv("HMM_MIN_CONF", "0.5"))
    if adj_conf < min_conf:
        logging.info(f"[HMM] {sym}: Low Confidence {adj_conf:.4f} < {min_conf} (Probs: {probs})")
        return None  # low confidence

    # Get current market price for reference (used in meta, not required for decision)
    px = 0.0

    quote = adjust_quote(sym, float(params.get("quote_usdt") or S.quote_usdt))
    
    # --- Institutional Volatility Targeting ---
    # Calc target size based on volatility
    # Assume we want to use the config quote as "Base Equity" per trade concept, 
    # or better, use account equity if available. For starter pack, use quote as base.
    base_equity = quote
    vol_mgr = _vol_managers[sym]
    target_exposure = vol_mgr.get_target_exposure(base_equity, cap_leverage=2.0)
    
    # If HMM confidence is high, we might scale up? 
    # "Half-Kelly" check logic could go here. 
    # For now, simply use VolTarget result as the notional.
    quote_sized = target_exposure

    if p_bull > p_bear and p_bull > p_chop:
        side = "BUY"
    elif p_bear > p_bull and p_bear > p_chop:
        side = "SELL"
    else:
        # e.g., chop is dominant
        logging.info(f"[HMM] {sym}: Chop Dominant (Probs: {probs})")
        return None

    _last_signal_ts[sym] = now
    meta = {
        "exp": "hmm_inst_v2",
        "probs": probs.tolist(),
        "mark": px,
        "conf": adj_conf,
        "cooldown": dynamic_cooldown,
        "vol_ann": vol_mgr.get_annualized_vol(),
        "algo": "chase", # Phase 1 Smart Exec
        "max_slippage": 0.01
    }
    if selection:
        meta["param_config_id"] = selection.get("config_id")
        meta["preset_id"] = selection.get("preset_id")
        meta["param_features"] = selection.get("features") or feature_payload
        meta["param_strategy"] = selection.get("strategy") or PARAM_STRATEGY
        meta["param_instrument"] = selection.get("instrument") or instrument
        meta["param_params"] = params
    return side, float(quote_sized), meta


# Wire hot-reload subscription
try:
    from engine.core.event_bus import BUS

    async def _handle_promotion(event: dict) -> None:
        reload_model(event)

    BUS.subscribe("model.promoted", _handle_promotion)
    print("[HMM] Wired hot-reload subscription.")
except Exception as e:
    print(f"[HMM] Failed to wire hot-reload: {e}")
