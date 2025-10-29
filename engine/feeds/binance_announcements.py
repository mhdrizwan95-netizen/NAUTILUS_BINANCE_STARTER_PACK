from __future__ import annotations

"""Minimal Binance announcement poller that feeds ``events.external_feed``.

The poller keeps legacy behaviour (environment gating, naive dedupe) but now
emits structured events through the shared signal queue so every subscriber –
Listing Sniper, Meme Sentiment, Event Breakout, etc. – receives identical
payloads.

The fetcher remains a stub; wire in a real HTTP client where
``_fetch_announcements`` currently returns an empty list.
"""

import asyncio
import logging
import os
import time
from typing import Dict, List

from engine.core.signal_queue import SIGNAL_QUEUE, QueuedEvent
from engine.metrics import (
    external_feed_events_total,
    external_feed_errors_total,
    external_feed_latency_seconds,
    external_feed_last_event_epoch,
)


LOGGER = logging.getLogger("engine.feeds.binance_announcements")
EVENT_SOURCE = "binance_announcements"
EVENT_TOPIC = "events.external_feed"
DEFAULT_PRIORITY = 0.85


async def _fetch_announcements() -> List[Dict]:
    """Placeholder fetcher – override with a real implementation."""

    return []


async def _publish(payload: Dict[str, object], *, priority: float = DEFAULT_PRIORITY) -> None:
    event = {
        "source": EVENT_SOURCE,
        "payload": payload,
        "asset_hints": [str(payload.get("symbol") or "") or None],
        "priority": priority,
    }
    # Drop empty asset hints (e.g. when symbol missing)
    hints = [hint for hint in event["asset_hints"] if hint]
    event["asset_hints"] = hints
    await SIGNAL_QUEUE.put(
        QueuedEvent(
            topic=EVENT_TOPIC,
            data=event,
            priority=priority,
            expires_at=None,
            source=EVENT_SOURCE,
        )
    )
    external_feed_events_total.labels(EVENT_SOURCE).inc()
    external_feed_last_event_epoch.labels(EVENT_SOURCE).set(time.time())


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
                        await _publish(payload)
                        seen[key] = now + ttl
                    except Exception as exc:  # noqa: BLE001
                        external_feed_errors_total.labels(EVENT_SOURCE).inc()
                        LOGGER.debug("binance announcement publish failed: %s", exc, exc_info=True)
        except Exception as exc:  # noqa: BLE001
            external_feed_errors_total.labels(EVENT_SOURCE).inc()
            LOGGER.warning("binance announcement loop error: %s", exc, exc_info=True)

        await asyncio.sleep(poll)
