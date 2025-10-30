import asyncio
import pytest

from engine.execution.execute import StrategyExecutor


class DummyRisk:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.requests = []

    def check_order(self, *, symbol, side, quote, quantity, market):
        self.requests.append((symbol, side, quote, quantity, market))
        if self.ok:
            return True, {}
        return False, {"error": "BLOCKED"}


class DummyRouter:
    def __init__(self):
        self.calls = []

    async def market_quote(self, symbol, side, quote, market=None):
        self.calls.append((symbol, side, quote, market))
        return {"avg_fill_price": 100.0, "filled_qty_base": quote / 100.0}


def test_executor_dry_run():
    risk = DummyRisk()
    router = DummyRouter()
    executor = StrategyExecutor(risk=risk, router=router, default_dry_run=True, source="test")
    result = asyncio.run(executor.execute({
        "strategy": "test",
        "symbol": "BTCUSDT.BINANCE",
        "side": "BUY",
        "quote": 50.0,
        "market": "spot",
        "tag": "demo",
        "ts": 123.0,
    }))
    assert result["status"] == "dry_run"
    assert not router.calls


def test_executor_submits_order():
    risk = DummyRisk(ok=True)
    router = DummyRouter()
    executor = StrategyExecutor(risk=risk, router=router, default_dry_run=False, source="test")
    result = asyncio.run(executor.execute({
        "strategy": "test",
        "symbol": "ETHUSDT.BINANCE",
        "side": "BUY",
        "quote": 100.0,
        "market": "spot",
        "tag": "demo",
        "ts": 999.0,
    }))
    assert result["status"] == "submitted"
    assert router.calls == [("ETHUSDT.BINANCE", "BUY", 100.0, "spot")]
    order = result["order"]
    assert order["result"]["filled_qty_base"] == pytest.approx(1.0)


def test_executor_rejects_via_risk():
    risk = DummyRisk(ok=False)
    router = DummyRouter()
    executor = StrategyExecutor(risk=risk, router=router, default_dry_run=False, source="test")
    result = asyncio.run(executor.execute({
        "strategy": "test",
        "symbol": "XRPUSDT.BINANCE",
        "side": "BUY",
        "quote": 25.0,
        "market": "spot",
        "tag": "demo",
        "ts": 1.0,
    }))
    assert result["status"] == "rejected"
    assert not router.calls
