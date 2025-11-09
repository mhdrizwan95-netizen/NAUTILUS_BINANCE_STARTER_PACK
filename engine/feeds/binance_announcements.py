"""Minimal Binance announcement poller that feeds ``events.external_feed``.

The poller keeps legacy behaviour (environment gating, naive dedupe) but now
emits structured events through the shared signal queue so every subscriber –
Listing Sniper, Meme Sentiment, Event Breakout, etc. – receives identical
payloads.

The fetcher remains a stub; wire in a real HTTP client where
``_fetch_announcements`` currently returns an empty list.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from engine.events.publisher import publish_external_event
from engine.events.schemas import ExternalEvent
from engine.metrics import (
    external_feed_errors_total,
    external_feed_latency_seconds,
)

LOGGER = logging.getLogger("engine.feeds.binance_announcements")
EVENT_SOURCE = "binance_announcements"
DEFAULT_PRIORITY = 0.85
_FETCH_ERRORS = (
    asyncio.TimeoutError,
    ConnectionError,
    RuntimeError,
    ValueError,
)
_PUBLISH_ERRORS = (
    RuntimeError,
    ValueError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    LOGGER.debug("%s suppressed: %s", context, exc, exc_info=True)


async def _fetch_announcements() -> list[dict]:
    """Placeholder fetcher – override with a real implementation."""

    return []


async def _publish(
    payload: dict[str, object],
    *,
    priority: float = DEFAULT_PRIORITY,
    ttl_sec: float | None = None,
) -> None:
    symbol_hint = str(payload.get("symbol") or "")
    asset_hints = [symbol_hint] if symbol_hint else []
    meta = {"priority": priority}
    if ttl_sec is not None:
        meta["ttl_sec"] = ttl_sec
    event = ExternalEvent(source=EVENT_SOURCE, payload=payload, meta=meta)
    await publish_external_event(
        event,
        priority=priority,
        expires_at=(time.time() + ttl_sec) if ttl_sec is not None else None,
        asset_hints=asset_hints,
    )


async def run() -> None:
    if os.getenv("ANN_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return

    poll = float(os.getenv("ANN_POLL_SEC", "45"))
    ttl = 24 * 60 * 60
    # Debounce by (id, ticker)
    seen: dict[str, float] = {}

    while True:
        started = time.perf_counter()
        try:
            # prune expired
            now = time.time()
            for key, expiry in list(seen.items()):
                if now >= expiry:
                    seen.pop(key, None)

            items = await _fetch_announcements()
            latency = time.perf_counter() - started
            external_feed_latency_seconds.labels(EVENT_SOURCE).observe(latency)

            for item in items:
                ann_id = str(item.get("id", ""))
                title = str(item.get("title", "")).lower()
                if not ann_id and not title:
                    continue

                tickers = list(item.get("tickers") or [])
                if not tickers:
                    # still debounce the id to avoid repeated processing
                    if ann_id:
                        seen.setdefault(ann_id, now + ttl)
                    continue

                # Recognise "will list" posts
                if "will list" not in title:
                    if ann_id:
                        seen.setdefault(ann_id, now + ttl)
                    continue

                for ticker in tickers:
                    key = f"{ann_id}:{ticker}" if ann_id else ticker
                    if key in seen:
                        continue

                    symbol = f"{ticker}USDT"
                    payload = {
                        "symbol": symbol.upper(),
                        "announcement": item,
                        "announced_at": item.get("time"),
                        "tickers": tickers,
                    }

                    try:
                        await _publish(payload, ttl_sec=ttl)
                        seen[key] = now + ttl
                    except _PUBLISH_ERRORS as exc:
                        external_feed_errors_total.labels(EVENT_SOURCE).inc()
                        _log_suppressed("binance_announcements.publish", exc)
        except _FETCH_ERRORS as exc:
            external_feed_errors_total.labels(EVENT_SOURCE).inc()
            LOGGER.warning("binance announcement loop error: %s", exc, exc_info=True)

        await asyncio.sleep(poll)
