import time
from types import SimpleNamespace

import pytest

from engine.metrics import generate_latest
from engine.strategies.social_sentiment import SocialSentimentConfig, SocialSentimentModule


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _RiskStub:
    def check_order(self, *, symbol, side, quote, quantity, market):  # noqa: D401
        return True, {}


class _RouterStub:
    def __init__(self):
        self.market_calls = []
        self.market_qty_calls = []
        self.tp_calls = []
        self.stop_calls = []
        self._portfolio = SimpleNamespace(state=SimpleNamespace(equity=50_000.0))

    async def market_quote(self, symbol, side, quote, market=None):
        self.market_calls.append((symbol, side, quote, market))
        return {"avg_fill_price": 0.1, "filled_qty_base": quote / 0.1}

    async def market_quantity(self, symbol, side, quantity, market=None):
        self.market_qty_calls.append((symbol, side, quantity, market))
        return {"avg_fill_price": 0.1, "filled_qty_base": quantity}

    async def amend_stop_reduce_only(self, symbol, side, stop_price, qty):
        self.stop_calls.append((symbol, side, stop_price, qty))

    async def place_reduce_only_limit(self, symbol, side, qty, price):
        self.tp_calls.append((symbol, side, qty, price))


class _RestStub:
    def __init__(self, bid=0.099, ask=0.101):
        self.bid = bid
        self.ask = ask

    def book_ticker(self, symbol):  # noqa: D401
        return {"bidPrice": str(self.bid), "askPrice": str(self.ask)}


class _Clock:
    def __init__(self):
        self.now = time.time()

    def time(self):  # noqa: D401
        return self.now


def _social_event(clock, sentiment=0.9, source="twitter"):
    return {
        "source": source,
        "asset_hints": ["DOGEUSDT"],
        "payload": {
            "text": "#DOGE 🚀🚀",
            "sentiment_score": sentiment,
            "mentions": 50,
            "metrics": {
                "like_count": 1200,
                "retweet_count": 600,
                "velocity": 20,
            },
            "created_at": clock.time(),
            "author": "elonmusk",
        },
        "timestamp": clock.time(),
    }


@pytest.mark.anyio
async def test_social_sentiment_executes_on_positive_event():
    clock = _Clock()
    router = _RouterStub()
    rest = _RestStub()
    cfg = SocialSentimentConfig(
        enabled=True,
        dry_run=False,
        min_signal_score=0.5,
        min_mentions=5.0,
        min_velocity=0.2,
        coin_cooldown_sec=60.0,
        influencers=("elonmusk",),
    )
    module = SocialSentimentModule(router, _RiskStub(), rest, cfg, clock=clock)

    await module.on_external_event(_social_event(clock))

    assert router.market_calls, "expected market order submission"
    assert router.stop_calls, "stop placement should be attempted"
    assert len(router.tp_calls) == len(cfg.take_profit_levels)

    metrics_blob = generate_latest().decode()
    assert "social_sentiment_events_total" in metrics_blob
    assert "social_sentiment_orders_total" in metrics_blob


@pytest.mark.anyio
async def test_social_sentiment_respects_coin_cooldown():
    clock = _Clock()
    router = _RouterStub()
    rest = _RestStub()
    cfg = SocialSentimentConfig(
        enabled=True,
        dry_run=False,
        min_signal_score=0.5,
        min_mentions=5.0,
        min_velocity=0.2,
        coin_cooldown_sec=600.0,
        influencers=("elonmusk",),
    )
    module = SocialSentimentModule(router, _RiskStub(), rest, cfg, clock=clock)

    evt = _social_event(clock)
    await module.on_external_event(evt)
    assert len(router.market_calls) == 1

    # Advance clock slightly but not beyond cooldown window
    clock.now += 30
    evt2 = _social_event(clock)
    await module.on_external_event(evt2)

    assert len(router.market_calls) == 1, "cooldown should suppress additional orders"

    metrics_blob = generate_latest().decode()
    assert "social_sentiment_events_total" in metrics_blob
