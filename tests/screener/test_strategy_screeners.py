import pytest

from screener import service


def _make_klines(prices, volumes):
    rows = []
    for price, vol in zip(prices, volumes):
        rows.append(
            [
                0,
                str(price),
                str(price * 1.01),
                str(price * 0.99),
                str(price),
                str(vol),
                0,
                str(price * vol),
            ]
        )
    return rows


def _build_test_data():
    trend_prices = []
    trend_price = 100.0
    for i in range(60):
        trend_price += 0.18
        if i % 7 == 0:
            trend_price -= 0.12
        trend_prices.append(trend_price)
    trend_vols = [900 + i * 12 for i in range(60)]
    scalp_prices = [50 + ((-1) ** i) * 0.03 for i in range(60)]
    scalp_vols = [1500] * 60
    momentum_prices = [30 + 0.05 * i for i in range(40)] + [32 + 0.9 * i for i in range(20)]
    momentum_vols = [250] * 40 + [2200] * 20
    meme_prices = [5 + 0.01 * i for i in range(55)] + [5.6, 6.2, 7.0, 7.8, 8.4]
    meme_vols = [80] * 55 + [1800, 2200, 2600, 3000, 3400]
    listing_prices = [2 + 0.04 * i for i in range(60)]
    listing_vols = [120] * 55 + [600, 650, 700, 750, 800]

    klines = {
        "TRENDUSDT": _make_klines(trend_prices, trend_vols),
        "SCALPUSDT": _make_klines(scalp_prices, scalp_vols),
        "MOMOUSDT": _make_klines(momentum_prices, momentum_vols),
        "MEMEUSDT": _make_klines(meme_prices, meme_vols),
        "LISTUSDT": _make_klines(listing_prices, listing_vols),
    }

    def _book(price, spread, depth):
        bids = [[f"{price - spread/2:.2f}", str(depth)]] * 5
        asks = [[f"{price + spread/2:.2f}", str(depth)]] * 5
        return {"bids": bids, "asks": asks}

    books = {
        "TRENDUSDT": _book(trend_prices[-1], 0.4, 2_500),
        "SCALPUSDT": _book(scalp_prices[-1], 0.02, 4_000),
        "MOMOUSDT": _book(momentum_prices[-1], 0.8, 1_800),
        "MEMEUSDT": _book(meme_prices[-1], 0.6, 600),
        "LISTUSDT": _book(listing_prices[-1], 0.5, 1_200),
    }

    universe = {
        "TRENDUSDT": {"quote_volume_24h": 1_500_000},
        "SCALPUSDT": {"quote_volume_24h": 2_000_000},
        "MOMOUSDT": {"quote_volume_24h": 1_200_000},
        "MEMEUSDT": {"quote_volume_24h": 350_000, "news_score": 5},
        "LISTUSDT": {"quote_volume_24h": 300_000, "listing_age_days": 2.0},
    }

    return klines, books, universe


@pytest.fixture(autouse=True)
def _reset_state():
    service._LAST_SCAN = {}
    yield
    service._LAST_SCAN = {}


def test_scan_produces_strategy_buckets(monkeypatch):
    klines, books, universe = _build_test_data()

    monkeypatch.setattr(service, "klines_1m", lambda sym, n=60: klines[sym])
    monkeypatch.setattr(service, "orderbook", lambda sym, limit=10: books[sym])
    monkeypatch.setattr(service, "get_universe", lambda: universe)

    snapshot = service.scan()

    strategies = snapshot["strategies"]
    assert "trend_follow" in strategies
    assert "scalping" in strategies
    assert "momentum_breakout" in strategies
    assert "meme_coin" in strategies
    assert "listing_sniper" in strategies

    def _top_entry(key):
        return strategies[key][0]

    assert _top_entry("trend_follow")["symbol"] == "TRENDUSDT"
    assert _top_entry("scalping")["symbol"] == "SCALPUSDT"
    assert _top_entry("momentum_breakout")["symbol"] == "MOMOUSDT"
    assert _top_entry("meme_coin")["symbol"] == "MEMEUSDT"
    assert _top_entry("listing_sniper")["symbol"] == "LISTUSDT"

    trend_signal = _top_entry("trend_follow")["signal"]
    assert trend_signal["strategy_id"] == "trend_follow"
    assert trend_signal["suggested_stop"] < trend_signal["suggested_tp"]

    meme_signal = _top_entry("meme_coin")["signal"]
    assert meme_signal["strategy_id"] == "meme_coin_sentiment"
    assert meme_signal["metadata"]["take_profit_ladder"]


def test_candidates_endpoint_returns_per_strategy(monkeypatch):
    klines, books, universe = _build_test_data()
    monkeypatch.setattr(service, "klines_1m", lambda sym, n=60: klines[sym])
    monkeypatch.setattr(service, "orderbook", lambda sym, limit=10: books[sym])
    monkeypatch.setattr(service, "get_universe", lambda: universe)

    service.scan()
    trend = service.candidates(strategy="trend_follow", limit=1)
    assert isinstance(trend, list) and trend
    assert trend[0]["symbol"] == "TRENDUSDT"
    assert trend[0]["signal"]["entry_mode"] in {"market", "limit_pullback"}

    meme = service.candidates(strategy="meme_coin")
    assert any(entry["symbol"] == "MEMEUSDT" for entry in meme)
    assert all("signal" in entry for entry in meme)

    default = service.candidates(limit=3)
    assert default == list(universe.keys())[:3]

    assert service.candidates(strategy="unknown") == []
