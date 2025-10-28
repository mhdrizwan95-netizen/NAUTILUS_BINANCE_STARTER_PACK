import types
import pytest

from engine.risk_guardian import GuardianConfig, RiskGuardian


class StubPosition:
    def __init__(self, symbol, qty, entry, stop, last):
        self.symbol = symbol
        self.quantity = qty
        self.entry = entry
        self.stop = stop
        self.last_price = last


class StubRouter:
    def __init__(self, positions=None, realized=0.0):
        positions = positions or {}
        self._state = types.SimpleNamespace(positions=positions, realized=realized)
        self.calls = []

    def portfolio_service(self):
        return types.SimpleNamespace(state=self._state)

    async def market_quantity(self, symbol, side, qty):
        self.calls.append((symbol, side, qty))


@pytest.mark.asyncio
async def test_guardian_soft_cross_health(monkeypatch, tmp_path):
    cfg = GuardianConfig(
        enabled=True,
        cross_health_floor=1.35,
        futures_mmr_floor=0.80,
        critical_ratio=1.07,
        max_daily_loss_usd=100.0,
        daily_reset_tz="UTC",
        daily_reset_hour=0,
    )
    guardian = RiskGuardian(cfg)
    router = StubRouter()

    events = []

    async def fake_publish(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr("engine.core.event_bus.publish_risk_event", fake_publish)

    try:
        snapshot = {"marginLevel": 1.30}  # Below floor -> soft breach
        await guardian._enforce_cross_health(router, snapshot)
        assert events, "Expected risk event emission"
        topic, payload = events[0]
        assert topic == "cross_health_soft"
        assert payload["floors"]["cross"] == pytest.approx(1.35)
    finally:
        events.clear()


@pytest.mark.asyncio
async def test_guardian_hard_cross_health_trims_var(monkeypatch, tmp_path):
    cfg = GuardianConfig(
        enabled=True,
        cross_health_floor=1.35,
        futures_mmr_floor=0.80,
        critical_ratio=1.07,
        max_daily_loss_usd=100.0,
        daily_reset_tz="UTC",
        daily_reset_hour=0,
        var_trim_pct=0.30,
    )
    guardian = RiskGuardian(cfg)
    position = StubPosition("ALT.BINANCE", 100.0, 1.0, 0.90, 1.0)
    router = StubRouter({"ALT.BINANCE": position})

    events = []

    async def fake_publish(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr("engine.core.event_bus.publish_risk_event", fake_publish)

    try:
        snapshot = {
            "marginLevel": 1.20,  # soft breach
            "totalMaintMargin": 50.0,
            "totalWalletBalance": 100.0,
            "totalUnrealizedProfit": 0.0,
        }
        await guardian._enforce_cross_health(router, snapshot)
        assert any(tag == "cross_health_hard" for tag, _ in events)
        assert router.calls, "Expected risk guardian to trim largest VAR position"
        symbol, side, qty = router.calls[0]
        assert symbol == "ALT.BINANCE"
        assert side == "SELL"
        assert qty == pytest.approx(30.0)
    finally:
        events.clear()


@pytest.mark.asyncio
async def test_guardian_daily_stop_sets_flag(monkeypatch, tmp_path):
    cfg = GuardianConfig(
        enabled=True,
        cross_health_floor=1.35,
        futures_mmr_floor=0.80,
        critical_ratio=1.07,
        max_daily_loss_usd=50.0,
        daily_reset_tz="UTC",
        daily_reset_hour=0,
    )
    guardian = RiskGuardian(cfg)
    router = StubRouter({}, realized=0.0)

    monkeypatch.chdir(tmp_path)
    await guardian._enforce_daily_stop(router)
    # Simulate subsequent loss crossing the limit
    router._state.realized = -75.0

    events = []

    async def fake_publish(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr("engine.core.event_bus.publish_risk_event", fake_publish)

    try:
        await guardian._enforce_daily_stop(router)
        flag_path = tmp_path / "state" / "trading_enabled.flag"
        assert flag_path.exists()
        assert flag_path.read_text().strip() == "false"
        assert events and events[0][0] == "daily_stop"
        assert events[0][1]["limit"] == pytest.approx(50.0)
    finally:
        events.clear()
