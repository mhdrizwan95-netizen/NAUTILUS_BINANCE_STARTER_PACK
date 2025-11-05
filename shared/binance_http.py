from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

import httpx

BINANCE_BASE = "https://api.binance.com"
_HEADERS = {"User-Agent": "nautilus-screener/1.0"}
_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)
_TIMEOUT = httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=5.0)
_MAX_ATTEMPTS = 4
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 4.0


def fetch_json(path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
    """Fetch JSON from the Binance REST API with retries and jitter."""
    target = f"{BINANCE_BASE}{path}"
    last_exc: Exception | None = None
    with httpx.Client(
        headers=_HEADERS,
        timeout=_TIMEOUT,
        limits=_LIMITS,
        trust_env=False,
    ) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = client.get(target, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt == _MAX_ATTEMPTS:
                    break
                sleep_for = min(
                    _BACKOFF_BASE * (2 ** (attempt - 1)),
                    _BACKOFF_CAP,
                )
                sleep_for += random.uniform(0.0, 0.3)
                time.sleep(sleep_for)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch Binance path {path}")


__all__ = ["fetch_json"]
