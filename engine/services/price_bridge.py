import asyncio
import logging
import os
from collections import deque

import httpx

from engine.core.event_bus import BUS

logger = logging.getLogger(__name__)


class PriceBridge:
    """
    Bridges internal engine price ticks to the Ops service via HTTP.
    Buffers ticks to avoid overwhelming the Ops service.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._bus = BUS
        # Assuming ops_url and token are now class attributes or obtained elsewhere
        # For example, from environment variables or passed during class instantiation
        # For this change, we'll assume they are defined in the class scope or globally
        # or will be set by another mechanism.
        self._ops_url = os.getenv("OPS_URL", "http://localhost:8000").rstrip("/")
        self._token = os.getenv("OPS_TOKEN", "default_token")
        self._buffer = deque()
        self._running = False
        self._task = None
        self._client = http_client if http_client else httpx.AsyncClient(timeout=1.0)

    async def start(self):
        self._running = True
        self._bus.subscribe("market.tick", self._on_tick)
        self._task = asyncio.create_task(self._flush_loop())
        logger.info("PriceBridge started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._client.aclose()
        logger.info("PriceBridge stopped")

    def _on_tick(self, topic: str, payload: dict):
        # Payload expected: {symbol, price, time, ...}
        self._buffer.append(payload)

    async def _flush_loop(self):
        while self._running:
            await asyncio.sleep(0.1)  # Flush every 100ms
            if not self._buffer:
                continue

            # Take latest tick per symbol to reduce noise
            latest = {}
            while self._buffer:
                tick = self._buffer.popleft()
                sym = tick.get("symbol")
                if sym:
                    latest[sym] = tick

            for tick in latest.values():
                try:
                    await self._client.post(
                        f"{self._ops_url}/api/events/price",
                        json=tick,
                        headers={"X-Ops-Token": self._token},
                    )
                except Exception as e:
                    logger.warning(f"Failed to push price tick: {e}")
