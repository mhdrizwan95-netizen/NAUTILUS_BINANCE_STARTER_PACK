# strategies/hmm_policy/telemetry_ops.py
from __future__ import annotations
import os, time, asyncio
from typing import Dict, Any, Optional

# Prefer httpx (async). If not available at runtime, fall back to requests (sync).
_USE_HTTPX = True
try:
    import httpx  # type: ignore
except Exception:
    _USE_HTTPX = False
    import requests  # type: ignore

OPS_BASE = os.getenv("OPS_BASE", "http://127.0.0.1:8001")
OPS_METRICS_ENDPOINT = f"{OPS_BASE}/metrics_snapshot"
OPS_API_TOKEN = os.getenv("OPS_API_TOKEN", "")  # optional

def _headers() -> Dict[str, str]:
    h = {"content-type": "application/json"}
    if OPS_API_TOKEN:
        h["X-OPS-TOKEN"] = OPS_API_TOKEN
    return h

async def publish_metrics_async(metrics: Dict[str, Any]) -> None:
    """Non-blocking publish (use inside async loops)."""
    payload = {
        "pnl_realized": float(metrics.get("pnl_realized", 0.0)),
        "pnl_unrealized": float(metrics.get("pnl_unrealized", 0.0)),
        "drift_score": float(metrics.get("drift_score", 0.0)),
        "policy_confidence": float(metrics.get("policy_confidence", 0.0)),
        "order_fill_ratio": float(metrics.get("order_fill_ratio", 0.0)),
        "venue_latency_ms": float(metrics.get("venue_latency_ms", 0.0)),
    }
    if _USE_HTTPX:
        timeout = httpx.Timeout(2.0, read=2.0)
        async with httpx.AsyncClient(timeout=timeout) as c:
            try:
                await c.post(OPS_METRICS_ENDPOINT, json=payload, headers=_headers())
            except Exception:
                # swallow network errors (telemetry should never break trading)
                pass
    else:
        try:
            requests.post(OPS_METRICS_ENDPOINT, json=payload, headers=_headers(), timeout=2.0)
        except Exception:
            pass

def publish_metrics_sync(metrics: Dict[str, Any]) -> None:
    """Safe to call from a synchronous loop; uses httpx in a background task if an event loop exists."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(publish_metrics_async(metrics))
        return
    except RuntimeError:
        # no running loop; do a best-effort sync POST
        try:
            if _USE_HTTPX:
                with httpx.Client(timeout=2.0) as c:  # type: ignore
                    c.post(OPS_METRICS_ENDPOINT, json=metrics, headers=_headers())
            else:
                requests.post(OPS_METRICS_ENDPOINT, json=metrics, headers=_headers(), timeout=2.0)  # type: ignore
        except Exception:
            pass

# Optional: small rate limiter to avoid flooding
_last_push_ts: float = 0.0
def publish_metrics_throttled(metrics: Dict[str, Any], min_interval_sec: float = 2.0) -> None:
    global _last_push_ts
    now = time.time()
    if now - _last_push_ts >= min_interval_sec:
        _last_push_ts = now
        publish_metrics_sync(metrics)
