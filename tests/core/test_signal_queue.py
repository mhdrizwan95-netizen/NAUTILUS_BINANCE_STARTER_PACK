import asyncio

import pytest

from engine.core.signal_queue import QueuedEvent, SignalPriorityQueue


class _BusStub:
    def __init__(self):
        self.calls = []

    async def publish(self, topic, data):
        self.calls.append((topic, data))


@pytest.mark.asyncio
async def test_signal_queue_dispatch_priority():
    bus = _BusStub()
    queue = SignalPriorityQueue()
    queue.start(bus)
    await queue.put(QueuedEvent(topic="t", data={"idx": 1}, priority=0.4))
    await queue.put(QueuedEvent(topic="t", data={"idx": 2}, priority=0.9))
    await asyncio.sleep(0.05)
    await queue.stop()
    assert [call[1]["idx"] for call in bus.calls] == [2, 1]
