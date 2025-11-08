import types

import pytest

from engine.guards.depeg_guard import DepegGuard


class _RouterStub:
    def __init__(self):
        self.trading_enabled = True
        self.reduce_calls = []

    async def set_trading_enabled(self, enabled: bool):
        self.trading_enabled = bool(enabled)

    async def list_positions(self):
        return []


class _BusStub:
    def __init__(self):
        self.fired = []

    def fire(self, topic, data):
        self.fired.append((topic, data))


@pytest.mark.asyncio
async def test_depeg_guard_triggers(monkeypatch):
    monkeypatch.setenv("DEPEG_GUARD_ENABLED", "true")
    monkeypatch.setenv("DEPEG_THRESHOLD_PCT", "0.5")
    monkeypatch.setenv("DEPEG_CONFIRM_WINDOWS", "2")
    monkeypatch.setenv("DEPEG_ACTION_COOLDOWN_MIN", "1")
    r = _RouterStub()
    bus = _BusStub()

    # md stub with USDTUSDC 0.992 (~0.8% deviation) and BTC parity ~1.0
    class _MD:
        def last(self, s):
            return {"USDTUSDC": 0.992, "BTCUSDT": 20000.0, "BTCUSDC": 20000.0}.get(s, 0.0)

    g = DepegGuard(r, md=_MD(), bus=bus, clock=types.SimpleNamespace(time=lambda: 1_700_000_000.0))

    await g.tick()  # confirm 1
    await g.tick()  # confirm 2 -> trigger
    assert r.trading_enabled is False
    assert any(t == "risk.depeg_trigger" for t, _ in bus.fired)
