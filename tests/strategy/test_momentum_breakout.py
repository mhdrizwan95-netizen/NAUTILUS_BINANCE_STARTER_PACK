import math

import pytest

from engine.metrics import generate_latest
from engine.strategies.momentum_breakout import MomentumBreakout, MomentumConfig


class _ClientStub:
    def __init__(self, bars):
        self._bars = bars

    async def klines(self, symbol, interval="1m", limit=30):
        return self._bars[-limit:]


class _RouterStub:
    def __init__(self, bars):
        self._client = _ClientStub(bars)
        self.orders = []
        self.trails = []
        self.limits = []

    def exchange_client(self):
        return self._client

    async def market_quote(self, symbol, side, quote, market=None):
        self.orders.append((symbol, side, quote, market))
        price = self._client._bars[-1][4]
        qty = quote / price
        return {"filled_qty_base": qty, "avg_fill_price": price}

    async def amend_stop_reduce_only(self, symbol, side, stop_price, qty):
        self.trails.append((symbol, side, stop_price, qty))

    async def place_reduce_only_limit(self, symbol, side, qty, price):
        self.limits.append((symbol, side, qty, price))

    def trade_symbols(self):
        return ["ABCUSDT"]


class _RiskStub:
    def check_order(self, *, symbol, side, quote, quantity=None, market=None):
        return True, {}


def _build_bars():
    bars = []
    price = 100.0
    for _ in range(12):
        bars.append([0, price, price * 1.01, price * 0.99, price, 900, 0, 120000])
    for i in range(6):
        price += 1.5
        bars.append([0, price, price * 1.02, price * 0.98, price, 2500, 0, 450000])
    return bars


@pytest.mark.asyncio
async def test_momentum_breakout_triggers_live_trade():
    bars = _build_bars()
    router = _RouterStub(bars)
    cfg = MomentumConfig(
        enabled=True,
        dry_run=False,
        use_scanner=False,
        symbols=["ABCUSDT"],
        scanner_top_n=5,
        interval_sec=30.0,
        lookback_bars=5,
        pct_move_threshold=0.01,
        volume_window=2,
        volume_baseline_window=5,
        volume_multiplier=1.2,
        atr_length=5,
        atr_interval="1m",
        stop_atr_mult=1.0,
        trail_atr_mult=1.0,
        take_profit_pct=0.02,
        cooldown_sec=120.0,
        notional_usd=100.0,
        max_extension_pct=0.2,
        prefer_futures=True,
        leverage_major=2,
        leverage_default=2,
        max_signals_per_cycle=3,
        min_quote_volume_usd=1000.0,
        default_market="futures",
    )
    momentum = MomentumBreakout(router, _RiskStub(), cfg=cfg, scanner=None)
    plan = await momentum._evaluate_symbol("ABCUSDT")
    assert plan is not None
    await momentum._execute(plan)
    assert router.orders, "market_quote should be invoked"
    symbol, side, quote, market = router.orders[0]
    assert symbol == "ABCUSDT.BINANCE"
    assert side == "BUY"
    assert math.isclose(quote, cfg.notional_usd)
    assert market == "futures"
    metrics_blob = generate_latest().decode()
    assert "momentum_breakout_candidates_total" in metrics_blob
    assert "momentum_breakout_orders_total" in metrics_blob
    # Cooldown prevents immediate re-entry
    again = await momentum._evaluate_symbol("ABCUSDT")
    assert again is None
