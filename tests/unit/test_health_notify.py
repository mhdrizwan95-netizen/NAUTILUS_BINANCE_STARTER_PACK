import types
import pytest

from engine.ops.health_notify import HealthNotifier


class FakeBus:
    def __init__(self):
        self.handlers = []

    def on(self, topic, fn):
        self.handlers.append(fn)

    def subscribe(self, topic, fn):
        self.on(topic, fn)


class FakeMetrics:
    class _C:
        def labels(self, *a):
            return self

        def inc(self, *a):
            return None

    health_transitions_total = _C()


class FakeClock:
    def __init__(self, t):
        self._t = float(t)

    def time(self):
        return self._t


class _TG:
    def __init__(self):
        self._count = 0

    async def send(self, text, parse_mode="Markdown"):
        self._count += 1


@pytest.mark.asyncio
async def test_health_notify_debounce():
    tg = _TG()
    bus = FakeBus()
    log = types.SimpleNamespace(warning=lambda *a, **k: None)
    clock = FakeClock(1000)
    cfg = {"HEALTH_TG_ENABLED": True, "HEALTH_DEBOUNCE_SEC": 10}
    hn = HealthNotifier(cfg, bus, tg, log, clock, FakeMetrics())
    # First transition sends
    await hn.on_health_state({"state": 2, "reason": "test"})
    # Second same-state quickly suppressed
    await hn.on_health_state({"state": 2, "reason": "dup"})
    assert tg._count == 1
