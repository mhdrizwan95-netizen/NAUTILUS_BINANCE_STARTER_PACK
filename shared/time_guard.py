from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("shared.time_guard")
logger.setLevel(logging.INFO)
logger.propagate = True

DEFAULT_ENDPOINT = "https://api.binance.com/api/v3/time"
DEFAULT_THRESHOLD_MS = 500
DEFAULT_TIMEOUT = 2.0


def check_clock_skew(component: str) -> int | None:
    """Compare local clock with a remote reference and log drift in milliseconds."""

    endpoint = os.getenv("CLOCK_SKEW_ENDPOINT", DEFAULT_ENDPOINT)
    threshold_ms = int(os.getenv("CLOCK_SKEW_THRESHOLD_MS", str(DEFAULT_THRESHOLD_MS)))
    timeout = float(os.getenv("CLOCK_SKEW_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT)))

    try:
        response = httpx.get(endpoint, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        remote_ms = _extract_epoch_ms(payload)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:  # pragma: no cover
        logger.warning(
            "clock_skew.check_failed",
            extra={"component": component, "endpoint": endpoint, "error": str(exc)},
        )
        return None

    local_ms = int(time.time() * 1000)
    drift = abs(local_ms - remote_ms)
    log_payload = {
        "component": component,
        "endpoint": endpoint,
        "drift_ms": drift,
        "threshold_ms": threshold_ms,
    }
    if drift > threshold_ms:
        logger.warning("clock_skew.drift_exceeded", extra=log_payload)
    else:
        logger.info("clock_skew.ok", extra=log_payload)
    return drift


def _extract_epoch_ms(payload: Any) -> int:
    """Handle the slightly different payload shapes returned by time APIs."""

    if isinstance(payload, dict):
        for key in ("serverTime", "timestamp", "epoch", "now"):
            value = payload.get(key)
            if value is not None:
                return int(value)
    if isinstance(payload, int | float):
        return int(payload)
    if isinstance(payload, str):
        return int(float(payload))
    logger.warning("clock_skew.payload_unparsed", extra={"payload": json.dumps(payload)})
    raise ValueError from None
