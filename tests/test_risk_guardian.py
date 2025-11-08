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
    def __init__(self, positions=None, realized=0.0, equity=0.0):
        positions = positions or {}
        self._state = types.SimpleNamespace(positions=positions, realized=realized, equity=equity)
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
async def test_guardian_daily_stop_uses_equity_pct(monkeypatch, tmp_path):
    # Ensure runtime-config-derived pct is honoured when no env override provided
    monkeypatch.delenv("MAX_DAILY_LOSS_USD", raising=False)
    monkeypatch.setattr(
        "engine.risk_guardian.load_runtime_config",
        lambda: types.SimpleNamespace(risk=types.SimpleNamespace(daily_stop_pct=0.06)),
    )
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
    router = StubRouter({}, realized=0.0, equity=50000.0)

    monkeypatch.chdir(tmp_path)
    await guardian._enforce_daily_stop(router)

    # Equity-based limit should be 3k (6% of 50k), larger than static 100
    router._state.realized = -3200.0
    events = []

    async def fake_publish(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr("engine.core.event_bus.publish_risk_event", fake_publish)
    try:
        await guardian._enforce_daily_stop(router)
        assert events and events[0][0] == "daily_stop"
        assert events[0][1]["limit"] == pytest.approx(3000.0, rel=1e-3)
    finally:
        events.clear()


@pytest.mark.asyncio
async def test_guardian_daily_stop_respects_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_DAILY_LOSS_USD", "500")
    monkeypatch.setattr(
        "engine.risk_guardian.load_runtime_config",
        lambda: types.SimpleNamespace(risk=types.SimpleNamespace(daily_stop_pct=0.10)),
    )
    cfg = GuardianConfig(
        enabled=True,
        cross_health_floor=1.35,
        futures_mmr_floor=0.80,
        critical_ratio=1.07,
        max_daily_loss_usd=200.0,
        daily_reset_tz="UTC",
        daily_reset_hour=0,
    )
    guardian = RiskGuardian(cfg)
    router = StubRouter({}, realized=0.0, equity=50000.0)

    monkeypatch.chdir(tmp_path)
    await guardian._enforce_daily_stop(router)

    router._state.realized = -600.0
    events = []

    async def fake_publish(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr("engine.core.event_bus.publish_risk_event", fake_publish)
    try:
        await guardian._enforce_daily_stop(router)
        assert events and events[0][0] == "daily_stop"
        # Env override should win over runtime pct (500 vs 5000)
        assert events[0][1]["limit"] == pytest.approx(500.0, rel=1e-3)
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
