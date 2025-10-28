import pytest

from engine.metrics import generate_latest
from engine.strategies.listing_sniper import ListingSniper, ListingSniperConfig
from engine.core.event_bus import BUS


class _RouterStub:
    async def market_quote(self, *_, **__):
        return {}


class _RiskStub:
    def check_order(self, **_):
        return True, {}


class _RestStub:
    pass


class _DexResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _DexClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return _DexResponse(self._payload)


@pytest.mark.asyncio
async def test_listing_sniper_emits_dex_candidate(monkeypatch):
    dex_payload = {
        "pairs": [
            {
                "chainId": "bsc",
                "pairAddress": "0xPAIR",
                "baseToken": {"symbol": "ABC", "address": "0xTOKEN"},
                "priceUsd": "1.25",
                "liquidity": {"usd": 500000},
                "fdv": "1500000",
                "volume": {"h1": "1200000", "h24": "4000000"},
                "priceChange": {"m5": "4.2"},
            }
        ]
    }

    from engine.strategies import listing_sniper as ls_mod

    monkeypatch.setattr(ls_mod.httpx, "AsyncClient", lambda **_: _DexClient(dex_payload))
    events = []

    async def fake_publish(topic, payload):
        events.append((topic, payload))

    monkeypatch.setattr(BUS, "publish", fake_publish)

    cfg = ListingSniperConfig(
        enabled=True,
        dry_run=True,
        dex_bridge_enabled=True,
        forward_legacy_event=False,
        metrics_enabled=False,
    )
    sniper = ListingSniper(_RouterStub(), _RiskStub(), _RestStub(), cfg)
    await sniper._maybe_emit_dex_candidate("ABCUSDT")

    assert events, "expected dex candidate event"
    topic, payload = events[0]
    assert topic == "strategy.dex_candidate"
    assert payload["addr"] == "0xTOKEN"
    assert payload["pair"] == "0xPAIR"
    assert payload["symbol"] == "ABC"


class _RouterMetricsStub:
    def __init__(self):
        self.calls = []

    async def market_quote(self, symbol, side, quote):
        self.calls.append((symbol, side, quote))
        return {"avg_fill_price": 1.01, "filled_qty_base": quote / 1.01}

    def exchange_client(self):
        class _Client:
            async def book_ticker(self, symbol):
                return {"bidPrice": "1.0", "askPrice": "1.01"}

            async def klines(self, symbol, interval="1m", limit=31):
                price = 1.0
                out = []
                for _ in range(limit):
                    out.append([0, price, price * 1.01, price * 0.99, price, 1000, 0, 250000])
                    price *= 1.001
                return out

        return _Client()

    async def amend_stop_reduce_only(self, *_, **__):
        return None

    async def place_reduce_only_limit(self, *_, **__):
        return None


class _RestMetricsStub:
    def book_ticker(self, symbol):
        return {"bidPrice": "1.0", "askPrice": "1.01"}

    def ticker_price(self, symbol):
        return {"price": "1.01"}


@pytest.mark.asyncio
async def test_listing_sniper_metrics_increment(monkeypatch):
    monkeypatch.setattr(BUS, "publish", lambda *_, **__: None)
    router = _RouterMetricsStub()
    cfg = ListingSniperConfig(
        enabled=True,
        dry_run=True,
        dex_bridge_enabled=False,
        forward_legacy_event=False,
        metrics_enabled=True,
        entry_delay_sec=0.0,
        price_poll_sec=0.01,
        max_chase_pct=0.5,
        max_spread_pct=0.05,
        cooldown_sec=1.0,
    )
    sniper = ListingSniper(router, _RiskStub(), _RestMetricsStub(), cfg)
    await sniper.on_external_event(
        {
            "source": "binance_listings",
            "payload": {"id": "xyz", "title": "Binance will list ABC", "tickers": ["ABC"], "published": 1690000000},
            "asset_hints": ["ABCUSDT"],
        }
    )
    metrics_blob = generate_latest().decode()
    assert "listing_sniper_announcements_total" in metrics_blob
    assert "listing_sniper_orders_total" in metrics_blob
