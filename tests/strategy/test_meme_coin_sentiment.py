from __future__ import annotations

import pytest

from engine.idempotency import CACHE

from engine.strategies.meme_coin_sentiment import MemeCoinConfig, MemeCoinSentiment


class _Clock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self._now = now

    def time(self) -> float:
        return self._now


class _PortfolioState:
    def __init__(self, equity: float) -> None:
        self.equity = equity


class _Portfolio:
    def __init__(self, equity: float) -> None:
        self.state = _PortfolioState(equity)


class _Router:
    def __init__(self, equity: float = 2_000.0) -> None:
        self._portfolio = _Portfolio(equity)
        self.calls: list[tuple[str, str, float, str | None]] = []

    async def market_quote(
        self, symbol: str, side: str, quote: float, market: str | None = None
    ):
        self.calls.append((symbol, side, quote, market))
        price = 0.1
        qty = quote / price
        return {"avg_fill_price": price, "filled_qty_base": qty}


class _Risk:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float, str | None]] = []

    def check_order(
        self,
        *,
        symbol: str,
        side: str,
        quote: float,
        quantity,
        market: str | None = None,
    ):
        self.calls.append((symbol, side, quote, market))
        return True, {}


class _RestClient:
    async def book_ticker(self, symbol: str):
        return {"bidPrice": "0.099", "askPrice": "0.101"}


@pytest.mark.asyncio
async def test_skips_when_priority_low():
    CACHE.cache.clear()
    router = _Router()
    risk = _Risk()
    rest = _RestClient()
    cfg = MemeCoinConfig(
        enabled=True,
        dry_run=True,
        min_priority=0.9,
        min_social_score=0.5,
        min_mentions=0,
        min_velocity_score=0.0,
    )
    strat = MemeCoinSentiment(router, risk, rest, cfg, clock=_Clock())
    event = {
        "source": "twitter_firehose",
        "priority": 0.5,
        "asset_hints": ["DOGE"],
        "payload": {
            "text": "#DOGE for fun",
            "metrics": {"like_count": 10, "retweet_count": 2},
            "social_velocity": 0.8,
        },
    }
    await strat.on_external_event(event)
    assert router.calls == []
    assert risk.calls == []


@pytest.mark.asyncio
async def test_places_order_for_high_score_event():
    CACHE.cache.clear()
    router = _Router()
    risk = _Risk()
    rest = _RestClient()
    cfg = MemeCoinConfig(
        enabled=True,
        dry_run=False,
        min_priority=0.8,
        min_social_score=0.5,
        min_mentions=5,
        min_velocity_score=0.5,
        per_trade_risk_pct=0.01,
        stop_loss_pct=0.1,
        cooldown_sec=300.0,
        trade_lock_sec=300.0,
    )
    strat = MemeCoinSentiment(router, risk, rest, cfg, clock=_Clock())
    event = {
        "source": "twitter_firehose",
        "priority": 0.95,
        "asset_hints": ["WOJAK"],
        "payload": {
            "text": "#WOJAK trending hard",
            "metrics": {
                "mention_count": 120,
                "like_count": 450,
                "retweet_count": 140,
                "reply_count": 60,
            },
            "social_velocity": 6.5,
            "price_change_pct": 18.0,
        },
    }
    await strat.on_external_event(event)
    assert len(router.calls) == 1
    symbol, side, notional, market = router.calls[0]
    assert symbol == "WOJAKUSDT.BINANCE"
    assert side == "BUY"
    assert notional > 0
    assert market == "spot"
    assert len(risk.calls) == 1
    assert strat._cooldowns.active("WOJAKUSDT", now=strat.clock.time())
