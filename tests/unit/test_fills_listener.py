import types
import pytest
import asyncio

from engine.ops.fills_listener import FillsListener


class E(types.SimpleNamespace):
    pass


class FakeWS:
    def __init__(self, events):
        self._events = events

    async def order_updates(self):
        for e in self._events:
            yield e


@pytest.mark.asyncio
async def test_ws_fills_emit():
    class Bus:
        def __init__(self):
            self.last = None

        def fire(self, t, p):
            self.last = (t, p)

    bus = Bus()
    ws = FakeWS(
        [
            E(
                event="executionReport",
                execution_type="TRADE",
                event_time=1700000000000,
                symbol="AAAUSDT",
                side="BUY",
                order_id="1",
                last_filled_qty=0.5,
                last_filled_price=10.0,
            )
        ]
    )
    fl = FillsListener(ws, bus, log=types.SimpleNamespace(warning=lambda *a, **k: None))

    async def consume_one():
        agen = fl.run()
        task = asyncio.create_task(agen)
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except Exception:
            pass

    await consume_one()
    assert bus.last is not None
    assert bus.last[0] == "trade.fill"
    assert bus.last[1]["symbol"] == "AAAUSDT"
