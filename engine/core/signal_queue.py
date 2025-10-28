from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class QueuedEvent:
    topic: str
    data: Dict[str, Any]
    priority: float
    expires_at: Optional[float] = None
    source: Optional[str] = None


class SignalPriorityQueue:
    """Priority queue for strategy/events with cooperative dispatcher."""

    def __init__(self) -> None:
        self._heap: list[Tuple[float, float, QueuedEvent]] = []
        self._cv = asyncio.Condition()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def put(self, event: QueuedEvent) -> None:
        score = -float(event.priority)
        async with self._cv:
            heapq.heappush(self._heap, (score, time.monotonic(), event))
            self._cv.notify()

    async def get(self) -> QueuedEvent:
        async with self._cv:
            while not self._heap:
                await self._cv.wait()
            _, _, evt = heapq.heappop(self._heap)
            return evt

    async def _dispatch_loop(self, bus) -> None:
        self._running = True
        try:
            while True:
                evt = await self.get()
                if evt.expires_at and float(evt.expires_at) < time.time():
                    continue
                try:
                    await bus.publish(evt.topic, evt.data)
                except Exception:
                    # Ignore downstream errors; keep loop alive
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def start(self, bus) -> None:
        if self._task and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._dispatch_loop(bus), name="signal-queue-dispatch")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


SIGNAL_QUEUE = SignalPriorityQueue()
