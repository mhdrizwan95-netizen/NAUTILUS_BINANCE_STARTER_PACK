from __future__ import annotations

import pytest

from engine.core.portfolio import Portfolio
from engine.runtime.config import RuntimeConfig
from engine.runtime.pipeline import ExecutionOrder, ExecutionRouter, RiskAllocator


class _StubRouter:
    def __init__(self, client, portfolio: Portfolio) -> None:
        self._client = client
        self._portfolio = portfolio

    def portfolio_service(self) -> Portfolio:
        return self._portfolio

    def exchange_client(self):  # noqa: ANN001
        return self._client


class _Client:
    def __init__(self, applied: int | None = None, mismatch: bool = False) -> None:
        self.applied = applied or 5
        self.mismatch = mismatch
        self.last_symbol = None
        self.leverage_calls = 0

    async def futures_change_leverage(self, symbol: str, leverage: int) -> dict:
        self.last_symbol = symbol.upper()
        self.leverage_calls += 1
        if self.mismatch:
            return {"symbol": symbol.upper(), "leverage": leverage + 1}
        return {"symbol": symbol.upper(), "leverage": self.applied}

    async def position_risk(self, *, market=None):  # noqa: ANN001
        return [{"symbol": "BTCUSDT", "leverage": self.applied}]


@pytest.mark.asyncio
async def test_ensure_leverage_configured_success():
    cfg = RuntimeConfig()
    portfolio = Portfolio(starting_cash=100_000)
    risk = RiskAllocator(cfg, portfolio)
    client = _Client(applied=7)
    router = ExecutionRouter(_StubRouter(client, portfolio), risk)
    order = ExecutionOrder(
        strategy="trend",
        symbol="BTCUSDT",
        side="BUY",
        venue="futures",
        notional_usd=1000.0,
        notional_fraction=0.05,
        bucket="futures_core",
        leverage=7,
        configured_leverage=7,
        effective_leverage=7,
        margin_fraction=0.01,
    )
    ok = await router._ensure_leverage("BTCUSDT", order)
    assert ok is True
    assert order.applied_leverage == 7
    assert order.leverage == 7


@pytest.mark.asyncio
async def test_ensure_leverage_configured_mismatch():
    cfg = RuntimeConfig()
    portfolio = Portfolio(starting_cash=100_000)
    risk = RiskAllocator(cfg, portfolio)
    client = _Client(applied=6, mismatch=True)
    router = ExecutionRouter(_StubRouter(client, portfolio), risk)
    order = ExecutionOrder(
        strategy="trend",
        symbol="BTCUSDT",
        side="BUY",
        venue="futures",
        notional_usd=1000.0,
        notional_fraction=0.05,
        bucket="futures_core",
        leverage=5,
        configured_leverage=5,
        effective_leverage=5,
        margin_fraction=0.01,
    )
    ok = await router._ensure_leverage("BTCUSDT", order)
    assert ok is False
    assert order.applied_leverage == 6


@pytest.mark.asyncio
async def test_ensure_leverage_default_path():
    cfg = RuntimeConfig()
    portfolio = Portfolio(starting_cash=100_000)
    risk = RiskAllocator(cfg, portfolio)
    client = _Client(applied=11)
    router = ExecutionRouter(_StubRouter(client, portfolio), risk)
    order = ExecutionOrder(
        strategy="momentum",
        symbol="BTCUSDT",
        side="BUY",
        venue="futures",
        notional_usd=500.0,
        notional_fraction=0.02,
        bucket="futures_core",
        leverage=1,
        configured_leverage=None,
        effective_leverage=3,
        margin_fraction=0.006,
    )
    ok = await router._ensure_leverage("BTCUSDT", order)
    assert ok is True
    assert order.applied_leverage == 11
    assert order.leverage == 11
