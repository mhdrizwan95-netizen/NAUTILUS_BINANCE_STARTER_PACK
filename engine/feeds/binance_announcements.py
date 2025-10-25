from __future__ import annotations

"""
Minimal Binance announcement poller (publish-only).

When ANN_ENABLED=true, polls at ANN_POLL_SEC and publishes
events.binance_listing with detected tickers for "will list" posts.

This is a stub: fetching/parsing logic should be replaced with a proper
source. Currently does nothing unless configured and network reachable.
"""

import asyncio
import os
from typing import Dict, List

from engine.core.event_bus import BUS


async def _fetch_announcements() -> List[Dict]:
    # Placeholder: return empty list. Extend with real fetcher.
    return []


async def run() -> None:
    if os.getenv("ANN_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return
    poll = float(os.getenv("ANN_POLL_SEC", "45"))
    # Debounce by (id,ticker) with TTL 24h
    seen: dict[str, float] = {}
    import time
    ttl = 24 * 60 * 60
    while True:
        try:
            # prune expired
            now = time.time()
            for k, v in list(seen.items()):
                if now >= v:
                    seen.pop(k, None)
            items = await _fetch_announcements()
            for it in items:
                _id = str(it.get("id", ""))
                if not _id or _id in seen:
                    # for multi-ticker dedupe, include ticker below
                    pass
                title = str(it.get("title", "")).lower()
                if "will list" in title:
                    tickers = list(it.get("tickers") or [])
                    for tk in tickers:
                        key = f"{_id}:{tk}"
                        if key in seen:
                            continue
                        try:
                            await BUS.publish("events.binance_listing", {"symbol": f"{tk}USDT", "time": it.get("time")})
                        except Exception:
                            pass
                        seen[key] = now + ttl
                else:
                    # Still debounce the id once to avoid repeated non-list items
                    seen[_id] = now + ttl
        except Exception:
            pass
        await asyncio.sleep(poll)
