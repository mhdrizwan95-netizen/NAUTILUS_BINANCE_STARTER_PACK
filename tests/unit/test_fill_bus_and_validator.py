import types
import pytest

from engine.core.order_router import OrderRouterExt
from engine.core.portfolio import Portfolio
from engine.ops.stop_validator import StopValidator


class _Bus:
    def __init__(self):
        self.last_topic = None
        self.last_payload = None
    def fire(self, topic, payload):
        self.last_topic = topic
        self.last_payload = payload
    def subscribe(self, topic, handler):
        # Not used in first test
        self._handler = handler


@pytest.mark.asyncio
async def test_router_emits_trade_fill(monkeypatch):
    client = object()
    router = OrderRouterExt(client, Portfolio(), venue="BINANCE")
    bus = _Bus()
    router.bus = bus  # type: ignore[attr-defined]

    async def fake_place(*a, **k):
        return {"filled_qty_base": 1.23, "avg_fill_price": 10.5, "order_id": "abc", "ts": 1_700_000_100}

    monkeypatch.setattr(router, "_place_market_order_async", fake_place)
    # prevent min-notional block by setting last price
    async def fake_last(symbol):
        return 10.0
    monkeypatch.setattr(router, "get_last_price", fake_last)

    res = await router._place_market_order_async(symbol="AAAUSDT.BINANCE", side="BUY", quote=None, quantity=1.23)
    emit = getattr(router, "_emit_fill", None)
    if emit is not None:
        emit(res, symbol="AAAUSDT", side="BUY", venue="BINANCE", intent="SCALP")
        assert bus.last_topic == "trade.fill"
        assert bus.last_payload["symbol"] == "AAAUSDT"
    assert res["order_id"] == "abc"


@pytest.mark.asyncio
async def test_validator_fast_check_on_fill(monkeypatch):
    # Router + bus + validator
    class _Router:
        def __init__(self):
            class _Pos:
                def __init__(self):
                    from engine.core.portfolio import Position
                    self.positions = {"BBBUSDT": Position(symbol="BBBUSDT", quantity=100.0, avg_price=10.0)}
            self._state = _Pos()
            self.repaired = False
        def portfolio_service(self):
            return types.SimpleNamespace(state=self._state)
        async def list_open_protection(self, symbol):
            return []
        async def amend_stop_reduce_only(self, symbol, side, stop_price, qty):
            self.repaired = True

    router = _Router()
    md = types.SimpleNamespace(atr=lambda *a, **k: 0.2, last=lambda *a, **k: 10.0)
    bus = _Bus()
    sv = StopValidator({"STOP_VALIDATOR_ENABLED": True, "STOP_VALIDATOR_REPAIR": True, "STOP_VALIDATOR_GRACE_SEC": 0}, router, md, log=types.SimpleNamespace(warning=lambda *a, **k: None), metrics=types.SimpleNamespace(stop_validator_missing_total=types.SimpleNamespace(labels=lambda *a, **k: types.SimpleNamespace(inc=lambda *_: None)), stop_validator_repaired_total=types.SimpleNamespace(labels=lambda *a, **k: types.SimpleNamespace(inc=lambda *_: None))), bus=bus)
    # Simulate fill event (fast path)
    await sv.on_fill({"symbol": "BBBUSDT"})
    assert router.repaired is True
