import asyncio

from engine.ops.health_guard import SoftBreachGuard


class DummyPosition:
    def __init__(self, symbol: str, quantity: float, avg_price: float) -> None:
        self.symbol = symbol
        self.quantity = quantity
        self.avg_price = avg_price


class DummyState:
    def __init__(self, positions: dict[str, DummyPosition]) -> None:
        self.positions = positions


class DummyPortfolio:
    def __init__(self, positions: dict[str, DummyPosition]) -> None:
        self.state = DummyState(positions)


class DummyRouter:
    def __init__(self, orders: list[dict]) -> None:
        self._orders = orders
        self.cancelled: list[dict] = []
        self.amended: list[tuple[str, str, float, float]] = []

    async def list_open_entries(self) -> list[dict]:
        return list(self._orders)

    async def cancel_open_order(self, order: dict) -> bool:
        self.cancelled.append(order)
        return True

    async def amend_stop_reduce_only(self, symbol: str, side: str, price: float, qty: float) -> None:
        self.amended.append((symbol, side, price, qty))


def test_soft_breach_guard_cancels_and_tightens(monkeypatch):
    monkeypatch.setenv("SOFT_BREACH_ENABLED", "true")
    monkeypatch.setenv("SOFT_BREACH_TIGHTEN_SL_PCT", "0.5")
    monkeypatch.setenv("SOFT_BREACH_BREAKEVEN_OK", "true")
    monkeypatch.setenv("SOFT_BREACH_CANCEL_ENTRIES", "true")

    entry_order = {"orderId": "e1", "symbol": "BTCUSDT", "type": "LIMIT", "side": "BUY"}
    stop_order = {
        "orderId": "s1",
        "symbol": "BTCUSDT",
        "type": "STOP_MARKET",
        "stopPrice": 29000.0,
        "reduceOnly": True,
    }
    router = DummyRouter([entry_order, stop_order])
    portfolio = DummyPortfolio({"BTCUSDT.BINANCE": DummyPosition("BTCUSDT.BINANCE", 0.01, 30000.0)})

    async def _noop_publish(*args, **kwargs):
        return None

    monkeypatch.setattr("engine.ops.health_guard.BUS.publish", _noop_publish)

    guard = SoftBreachGuard(router, portfolio)

    asyncio.run(guard.on_cross_health_soft({"kind": "test"}))

    assert entry_order in router.cancelled
    assert router.amended, "expected stop amend"
    _, _, new_price, _ = router.amended[-1]
    assert new_price > stop_order["stopPrice"]
    assert new_price <= portfolio.state.positions["BTCUSDT.BINANCE"].avg_price
