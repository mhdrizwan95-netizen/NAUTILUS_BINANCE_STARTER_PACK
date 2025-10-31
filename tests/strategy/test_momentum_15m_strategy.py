from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.strategies.momentum_15m import Momentum15mConfig, Momentum15mStrategy


class _DummyPortfolioState:
    def __init__(self):
        self.positions: dict[str, SimpleNamespace] = {}


class _DummyPortfolio:
    def __init__(self):
        self.state = _DummyPortfolioState()


class _DummyRouter:
    def __init__(self):
        self.orders = []
        self._portfolio = _DummyPortfolio()

    def place_market_order(self, *, symbol: str, side: str, quote, quantity, market=None):
        base = symbol.split(".")[0].upper()
        quantity = float(quantity or 0.0)
        if quantity <= 0:
            raise AssertionError("quantity must be positive")
        if side == "BUY":
            pos = self._portfolio.state.positions.get(base)
            if pos is None:
                pos = SimpleNamespace(quantity=0.0)
                self._portfolio.state.positions[base] = pos
            pos.quantity = float(pos.quantity) + quantity
        elif side == "SELL":
            pos = self._portfolio.state.positions.get(base)
            if pos is None:
                pos = SimpleNamespace(quantity=0.0)
                self._portfolio.state.positions[base] = pos
            pos.quantity = max(0.0, float(pos.quantity) - quantity)
        self.orders.append({"symbol": symbol, "side": side, "quantity": quantity})
        return {"status": "submitted", "filled_qty_base": quantity, "avg_fill_price": 1.0}

    def portfolio_service(self):
        return self._portfolio


class _DummyRisk:
    def check_order(self, *, symbol, side, quote, quantity, market=None):
        return True, {}


@pytest.fixture
def strategy():
    cfg = Momentum15mConfig(
        enabled=True,
        dry_run=False,
        symbol="PI_XBTUSD.KRAKEN",
        lookback_ticks=3,
        quantity=2.0,
        allow_shorts=False,
        rearm_sec=0.5,
    )
    router = _DummyRouter()
    strat = Momentum15mStrategy(router=router, risk=_DummyRisk(), cfg=cfg)
    return strat, router


def test_momentum_15m_triggers_breakout_and_flatten(strategy):
    strat, router = strategy
    sym = "PI_XBTUSD.KRAKEN"

    strat.on_tick(sym, 100.0, ts=0.0)
    strat.on_tick(sym, 101.0, ts=1.0)
    assert router.orders == []

    strat.on_tick(sym, 110.0, ts=2.0)
    assert len(router.orders) == 1
    assert router.orders[0]["side"] == "BUY"
    assert router.orders[0]["quantity"] == pytest.approx(2.0)

    strat.on_tick(sym, 112.0, ts=3.0)
    assert len(router.orders) == 1  # no duplicate buys

    strat.on_tick(sym, 95.0, ts=5.0)
    assert len(router.orders) == 2
    assert router.orders[-1]["side"] == "SELL"
    assert router.orders[-1]["quantity"] == pytest.approx(2.0)
