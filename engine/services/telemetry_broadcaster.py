import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger("telemetry_broadcaster")

class TelemetryBroadcaster:
    """
    Broadcasts telemetry updates to connected WebSocket clients.
    """
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to telemetry updates."""
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from telemetry updates."""
        self._subscribers.discard(queue)

    async def broadcast(self, payload: dict[str, Any]):
        """Broadcast a payload to all subscribers."""
        if not self._subscribers:
            return
        
        # _LOGGER.debug(f"[Telemetry] Broadcasting to {len(self._subscribers)} clients")
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                _LOGGER.warning("[Telemetry] Subscriber queue full, dropping message.")
                # Optional: disconnect slow consumer
                pass

# Global instance
BROADCASTER = TelemetryBroadcaster()
