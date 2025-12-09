"""Inference module for HMM predictions."""

import logging
import os
import threading
import time
from typing import Any

import numpy as np

from . import model_store

logger = logging.getLogger(__name__)

# Cached model for inference
_model_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()
_watchdog_running = False


def predict_proba(logret: list[float]) -> dict[str, Any]:
    """Predict regime probabilities from log returns.
    
    Args:
        logret: List of log returns (features)
        
    Returns:
        Dict with probs, regime, and confidence
    """
    model = _get_model()
    
    if model is None:
        # No model loaded, return neutral
        return {
            "probs": [0.33, 0.33, 0.34],
            "regime": "CHOP",
            "confidence": 0.34,
        }
    
    try:
        # Convert to numpy and reshape
        X = np.array(logret).reshape(-1, 1) if logret else np.array([[0.0]])
        
        # Get probabilities
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(X)[-1].tolist()
        else:
            # Mock model fallback
            n_states = getattr(model, "n_components", 3)
            probs = [1.0 / n_states] * n_states
        
        # Map to regime
        if len(probs) >= 3:
            p_bull, p_bear, p_chop = probs[0], probs[1], probs[2]
        elif len(probs) == 2:
            p_bull, p_bear = probs
            p_chop = 0.0
        else:
            p_bull = probs[0] if probs else 0.33
            p_bear = 0.33
            p_chop = 0.34
        
        if p_bull > p_bear and p_bull > p_chop:
            regime = "BULL"
            confidence = p_bull
        elif p_bear > p_bull and p_bear > p_chop:
            regime = "BEAR"
            confidence = p_bear
        else:
            regime = "CHOP"
            confidence = p_chop
        
        return {
            "probs": probs,
            "regime": regime,
            "confidence": float(confidence),
        }
        
    except Exception as e:
        logger.warning("Prediction failed: %s", e)
        return {
            "probs": [0.33, 0.33, 0.34],
            "regime": "CHOP",
            "confidence": 0.34,
            "error": str(e),
        }


def _get_model() -> Any:
    """Get the cached model or load from store."""
    with _cache_lock:
        if "model" in _model_cache:
            return _model_cache["model"]
    
    # Load from store
    model, scaler, meta = model_store.load_current()
    
    with _cache_lock:
        _model_cache["model"] = model
        _model_cache["scaler"] = scaler
        _model_cache["meta"] = meta
    
    return model


def reload_model() -> None:
    """Clear the cache and reload model."""
    with _cache_lock:
        _model_cache.clear()
    
    # Trigger reload
    _get_model()
    logger.info("Model reloaded from store")


def start_watchdog() -> None:
    """Start a background thread to watch for model updates."""
    global _watchdog_running
    
    if _watchdog_running:
        return
    
    interval = float(os.getenv("MODEL_WATCH_INTERVAL", "30"))
    
    def _watch():
        global _watchdog_running
        _watchdog_running = True
        last_reload = time.time()
        
        while _watchdog_running:
            try:
                # Periodically refresh model cache
                time.sleep(interval)
                
                # Check if model file was updated
                # (simple approach: reload every interval)
                reload_model()
                
            except Exception as e:
                logger.warning("Watchdog error: %s", e)
                time.sleep(5)
    
    thread = threading.Thread(target=_watch, daemon=True, name="model-watchdog")
    thread.start()
    logger.info("Model watchdog started (interval=%ss)", interval)
