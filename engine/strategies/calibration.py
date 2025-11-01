from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Any

CALIBRATION_PATH = Path(
    os.getenv("HMM_CALIBRATION_PATH", "engine/models/hmm_calibration.json")
)
_DEFAULT_PROFILE: Dict[str, Any] = {
    "confidence_gain": 1.0,
    "quote_multiplier": 1.0,
    "cooldown_scale": 1.0,
}
_CACHE_TTL = float(os.getenv("HMM_CALIBRATION_TTL_SEC", "60"))
_cache: Dict[str, Any] = {"ts": 0.0, "data": {}}


def _load_file() -> Dict[str, Any]:
    if not CALIBRATION_PATH.exists():
        return {}
    try:
        with CALIBRATION_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return {k.upper(): v for k, v in data.items()}
    except Exception:
        pass
    return {}


def _data() -> Dict[str, Any]:
    now = time.time()
    if now - _cache["ts"] > _CACHE_TTL:
        _cache["data"] = _load_file()
        _cache["ts"] = now
    return _cache["data"]


def profile(symbol: str) -> Dict[str, Any]:
    data = _data()
    sym = symbol.upper()
    return data.get(sym) or data.get("*") or _DEFAULT_PROFILE


def adjust_confidence(symbol: str, conf: float) -> float:
    info = profile(symbol)
    gain = float(info.get("confidence_gain", 1.0))
    return conf * gain


def adjust_quote(symbol: str, quote: float) -> float:
    info = profile(symbol)
    mult = float(info.get("quote_multiplier", 1.0))
    return quote * mult


def cooldown_scale(symbol: str) -> float:
    info = profile(symbol)
    return float(info.get("cooldown_scale", 1.0))


def snapshot() -> Dict[str, Any]:
    """Expose current calibration set for introspection/testing."""
    return {"path": str(CALIBRATION_PATH), "profiles": _data()}
