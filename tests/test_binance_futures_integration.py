import importlib
from urllib.parse import parse_qs

import httpx
import pytest
import respx


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch):
    """Ensure engine settings pick up env changes per test."""
    # Default demo futures configuration
    monkeypatch.setenv("VENUE", "BINANCE")
    monkeypatch.setenv("BINANCE_MODE", "futures_demo")
    monkeypatch.setenv("BINANCE_FUTURES_BASE", "https://testnet.binancefuture.com")
    monkeypatch.setenv("DEMO_API_KEY", "demo-key")
    monkeypatch.setenv("DEMO_API_SECRET", "demo-secret")
    monkeypatch.setenv("BINANCE_API_KEY", "demo-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "demo-secret")
    monkeypatch.setenv("TRADING_ENABLED", "false")

    from engine import config

    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
    importlib.reload(config)


def test_futures_demo_settings_use_testnet_base():
    from engine.config import get_settings, load_risk_config

    settings = get_settings()
    assert settings.is_futures is True
    assert settings.mode == "futures_demo"
    assert settings.base_url == "https://testnet.binancefuture.com"
    assert settings.api_key == "demo-key"

    risk = load_risk_config()
    # Futures defaults lift the min notional unless overridden
    assert risk.min_notional_usdt == pytest.approx(100.0)


@pytest.mark.anyio
@respx.mock
async def test_ticker_price_hits_premium_index():
    from engine.core.binance import BinanceREST

    route = respx.get("https://testnet.binancefuture.com/fapi/v1/premiumIndex").mock(
        return_value=httpx.Response(
            200, json={"symbol": "BTCUSDT", "markPrice": "25000.0"}
        )
    )

    client = BinanceREST()
    price = await client.ticker_price("BTCUSDT")

    assert route.called
    assert price == pytest.approx(25000.0)


@pytest.mark.anyio
@respx.mock
async def test_market_order_calls_futures_endpoint():
    from engine.core.binance import BinanceREST

    route = respx.post("https://testnet.binancefuture.com/fapi/v1/order").mock(
        return_value=httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "avgPrice": "25000.0",
                "executedQty": "0.001",
                "side": "BUY",
            },
        )
    )

    client = BinanceREST()
    resp = await client.submit_market_order("BTCUSDT", "BUY", 0.001)

    assert route.called
    assert resp["status"] == "FILLED"

    request = route.calls[0].request
    assert request.headers.get("X-MBX-APIKEY") == "demo-key"
    payload = parse_qs(request.content.decode())
    assert payload["symbol"] == ["BTCUSDT"]
    assert payload["type"] == ["MARKET"]
    assert payload["side"] == ["BUY"]
    assert "signature" in payload


@pytest.mark.anyio
@respx.mock
async def test_account_snapshot_uses_futures_path():
    from engine.core.binance import BinanceREST

    route = respx.get("https://testnet.binancefuture.com/fapi/v2/account").mock(
        return_value=httpx.Response(
            200,
            json={
                "totalWalletBalance": "1000.0",
                "positions": [],
                "assets": [{"asset": "USDT", "walletBalance": "1000.0"}],
            },
        )
    )

    client = BinanceREST()
    data = await client.account_snapshot()

    assert route.called
    assert data["totalWalletBalance"] == "1000.0"
