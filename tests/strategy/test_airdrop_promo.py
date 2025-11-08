from __future__ import annotations

import pytest

from engine.strategies.airdrop_promo import AirdropPromoConfig, AirdropPromoWatcher


class _Clock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self._now = now

    def time(self) -> float:
        return self._now


class _Router:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    async def market_quote(
        self, symbol: str, side: str, notional: float, market: str | None = None
    ) -> dict[str, float]:
        self.calls.append((symbol, side, notional, market))
        return {"avg_fill_price": 1.0, "filled_qty_base": notional}


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
    ) -> tuple[bool, dict]:
        self.calls.append((symbol, side, quote, market))
        return True, {}


class _RestClient:
    async def book_ticker(self, symbol: str) -> dict[str, str]:
        return {"bidPrice": "0.99", "askPrice": "1.01"}


@pytest.mark.asyncio
async def test_skips_when_no_keywords():
    cfg = AirdropPromoConfig(
        enabled=True,
        dry_run=False,
        min_priority=0.6,
        min_expected_reward_usd=5.0,
    )
    watcher = AirdropPromoWatcher(_Router(), _Risk(), _RestClient(), cfg, clock=_Clock())
    event = {
        "source": "binance_listings",
        "priority": 0.9,
        "asset_hints": ["ABC"],
        "payload": {
            "title": "Binance adds support for new trading pair ABC/USDT",
            "id": "abc-announce",
        },
    }
    await watcher.on_external_event(event)
    assert watcher.router.calls == []


@pytest.mark.asyncio
async def test_places_order_for_valid_promo():
    router = _Router()
    risk = _Risk()
    cfg = AirdropPromoConfig(
        enabled=True,
        dry_run=False,
        min_priority=0.6,
        min_expected_reward_usd=5.0,
        notional_max_usd=120.0,
    )
    watcher = AirdropPromoWatcher(router, risk, _RestClient(), cfg, clock=_Clock())
    event = {
        "source": "binance_listings",
        "priority": 0.92,
        "asset_hints": ["XYZ"],
        "payload": {
            "title": "Limited Promotion: Trade at least $60 of XYZ to receive $20 airdrop voucher",
            "id": "promo-xyz",
            "url": "https://www.binance.com/en/support/promo-xyz",
        },
    }
    await watcher.on_external_event(event)

    assert len(router.calls) == 1
    symbol, side, notional, market = router.calls[0]
    assert symbol == "XYZUSDT.BINANCE"
    assert side == "BUY"
    assert pytest.approx(notional, rel=1e-6) == 60.0
    assert market == "spot"
    assert len(risk.calls) == 1


@pytest.mark.asyncio
async def test_dry_run_executes_without_router():
    router = _Router()
    risk = _Risk()
    cfg = AirdropPromoConfig(
        enabled=True,
        dry_run=True,
        min_priority=0.6,
        min_expected_reward_usd=5.0,
        default_notional_usd=40.0,
    )
    watcher = AirdropPromoWatcher(router, risk, _RestClient(), cfg, clock=_Clock())
    event = {
        "source": "binance_listings",
        "priority": 0.85,
        "asset_hints": ["DEF"],
        "payload": {
            "title": "Binance Launchpool: Stake DEF and trade at least $40 to get $10 reward airdrop",
            "id": "promo-def",
        },
    }
    await watcher.on_external_event(event)

    assert router.calls == []
    assert len(risk.calls) == 1
