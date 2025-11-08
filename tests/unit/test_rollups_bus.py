import asyncio
import types

import pytest

from engine.telemetry.rollups import EventBORollup


class FakeBus:
    def __init__(self):
        self.handlers = {}

    def on(self, topic, fn):
        self.handlers.setdefault(topic, []).append(fn)

    async def emit(self, topic, payload):
        for fn in self.handlers.get(topic, []):
            r = fn(payload)
            if asyncio.iscoroutine(r):
                await r


@pytest.mark.asyncio
async def test_rollups_increment_on_bus_events():
    clock = types.SimpleNamespace(time=lambda: 1_700_000_000)
    rollups = EventBORollup(clock)
    bus = FakeBus()

    bus.on("event_bo.plan_dry", lambda p: rollups.inc("plans_dry", p["symbol"]))
    bus.on("event_bo.plan_live", lambda p: rollups.inc("plans_live", p["symbol"]))
    bus.on("event_bo.trade", lambda p: rollups.inc("trades", p["symbol"]))
    bus.on("event_bo.skip", lambda p: rollups.inc(f"skip_{p['reason']}", p["symbol"]))
    bus.on("event_bo.half", lambda p: rollups.inc("half_applied", p["symbol"]))
    bus.on("event_bo.trail", lambda p: rollups.inc("trail_update", p["symbol"]))

    await bus.emit("event_bo.plan_dry", {"symbol": "AAAUSDT"})
    await bus.emit("event_bo.plan_live", {"symbol": "AAAUSDT"})
    await bus.emit("event_bo.trade", {"symbol": "AAAUSDT"})
    await bus.emit("event_bo.skip", {"symbol": "BBBUSDT", "reason": "late_chase"})
    await bus.emit("event_bo.half", {"symbol": "AAAUSDT"})
    await bus.emit("event_bo.trail", {"symbol": "AAAUSDT"})

    assert rollups.cnt["plans_dry"] == 1
    assert rollups.cnt["plans_live"] == 1
    assert rollups.cnt["trades"] == 1
    assert rollups.cnt["skip_late_chase"] == 1
    assert rollups.cnt["half_applied"] == 1
    assert rollups.cnt["trail_update"] == 1
    assert rollups.top_symbols("trades")[0] == ("AAAUSDT", 1)
