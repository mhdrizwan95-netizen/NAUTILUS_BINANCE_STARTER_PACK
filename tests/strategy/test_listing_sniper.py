from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from engine.metrics import generate_latest
from engine.strategies.listing_sniper import ListingSniper, ListingSniperConfig


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _RiskStub:
    def check_order(self, *, symbol: str, side: str, quote, quantity=None, market=None):
        return True, {}


class _RestPriceStub:
    def __init__(self, bid: float = 1.0, ask: float = 1.01):
        self._bid = bid
        self._ask = ask

    def book_ticker(self, symbol):
        return {"bidPrice": str(self._bid), "askPrice": str(self._ask)}

    def ticker_price(self, symbol):
        return {"price": str((self._bid + self._ask) / 2.0)}


class _RouterPlanStub:
    def __init__(self):
        self.market_calls = []
        self.tp_calls = []
        self.stop_calls = []
        self.called_at: float | None = None
        self._event = asyncio.Event()
        self._portfolio = SimpleNamespace(state=SimpleNamespace(equity=25_000.0))

    async def market_quote(self, symbol, side, quote, market=None):
        self.called_at = time.time()
        self.market_calls.append((symbol, side, quote, market))
        self._event.set()
        return {"avg_fill_price": 1.0, "filled_qty_base": 10.0}

    async def place_reduce_only_limit(self, symbol, side, qty, price):
        self.tp_calls.append((symbol, side, qty, price))

    async def amend_stop_reduce_only(self, symbol, side, stop_price, qty):
        self.stop_calls.append((symbol, side, stop_price, qty))

    def round_tick(self, symbol, price):
        return round(price, 6)


@pytest.mark.anyio
async def test_listing_sniper_schedules_for_go_live_and_bracket(monkeypatch):
    router = _RouterPlanStub()
    rest = _RestPriceStub()
    cfg = ListingSniperConfig(
        enabled=True,
        dry_run=False,
        entry_delay_sec=0.05,
        entry_timeout_sec=1.0,
        price_poll_sec=0.01,
        take_profit_levels=(0.5, 1.0),
        cooldown_sec=0.0,
        max_spread_pct=0.2,
        max_chase_pct=0.9,
    )
    sniper = ListingSniper(router, _RiskStub(), rest, cfg)

    go_live = datetime.now(timezone.utc) + timedelta(seconds=0.1)
    event = {
        "source": "binance_listings",
        "payload": {
            "id": "abc-123",
            "title": "Binance will list TEST",
            "tickers": ["TEST"],
            "published": int(time.time()),
            "content": f"Trading will open at {go_live.strftime('%Y-%m-%d %H:%M:%S')} (UTC)",
        },
        "asset_hints": ["TESTUSDT"],
    }

    await sniper.on_external_event(event)
    await asyncio.wait_for(router._event.wait(), timeout=3)

    assert router.market_calls, "expected market order submission"
    go_live_ts = go_live.timestamp()
    assert router.called_at is not None
    # Allow small scheduling jitter
    assert router.called_at >= go_live_ts + cfg.entry_delay_sec - 0.05
    assert len(router.tp_calls) == len(cfg.take_profit_levels)
    tp_prices = sorted(price for _, _, _, price in router.tp_calls)
    assert tp_prices[0] == pytest.approx(1.5, rel=1e-3)
    assert tp_prices[-1] == pytest.approx(2.0, rel=1e-3)
    assert router.stop_calls, "expected protective stop placement"

    metrics_blob = generate_latest().decode()
    assert "listing_sniper_go_live_epoch" in metrics_blob

    await sniper.shutdown()
