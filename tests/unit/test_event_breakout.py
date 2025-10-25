import logging
import pytest

from engine.strategies.event_breakout import EventBreakout, BreakoutConfig


class _MD:
    def __init__(self, price=10.0, quote_last=600000.0, spread_bps=60.0, ch30=0.0):
        self._price = price
        self._quote_last = quote_last
        self._spread = spread_bps / 10000.0
        self._ch30 = ch30

    def last(self, symbol):
        return self._price

    def klines(self, symbol, interval, limit):
        # Build 31 klines: [ot, o, h, l, c, v, ct, qv]
        o = self._price
        c0 = o
        cN = o * (1 + self._ch30)
        arr = []
        for i in range(limit):
            close = cN if i == limit - 1 else c0
            arr.append([0, o, o * 1.01, o * 0.99, close, 1000, 0, self._quote_last])
        return arr

    def book_ticker(self, symbol):
        mid = self._price
        half = mid * self._spread / 2
        return {"bidPrice": mid - half, "askPrice": mid + half}


class _RouterStub:
    async def get_last_price(self, symbol):
        return 10.0

    def round_step(self, symbol, qty):
        return qty

    def round_tick(self, symbol, px):
        return px


@pytest.mark.asyncio
async def test_event_breakout_half_size_logs(caplog):
    caplog.set_level(logging.INFO)
    cfg = BreakoutConfig(enabled=True, dry_run=True, size_usd=120.0, half_size_minutes=5)
    md = _MD(price=10.0, quote_last=600000.0, spread_bps=60.0, ch30=0.0)
    router = _RouterStub()
    bo = EventBreakout(router, md=md, cfg=cfg)
    now_ms = time_ms()
    await bo.on_event({"symbol": "ABCUSDT", "time": now_ms})
    # Look for notional=$60 in logs
    assert any("[EVENT-BO:DRY] ABCUSDT" in r.message and "notional=$60" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_event_breakout_guardrails_late_chase(caplog):
    caplog.set_level(logging.INFO)
    cfg = BreakoutConfig(enabled=True, dry_run=True)
    md = _MD(price=10.0, quote_last=600000.0, spread_bps=20.0, ch30=0.25)  # 25% 30m change
    router = _RouterStub()
    bo = EventBreakout(router, md=md, cfg=cfg)
    await bo.on_event({"symbol": "XYZUSDT", "time": time_ms()})
    # Should skip due to late-chase
    assert any("late-chase" in r.message for r in caplog.records)


def time_ms():
    import time as _t
    return int(_t.time() * 1000)

