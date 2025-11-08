import importlib
import os

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from ops.aggregate_exposure import aggregate_exposure


@pytest.fixture(autouse=True)
def _env_clear(monkeypatch):
    for key in ["ENGINE_ENDPOINTS", "OPS_IBKR_TICKERS"]:
        if key in os.environ:
            monkeypatch.delenv(key, raising=False)


def mk_client(endpoints: str):
    os.environ["ENGINE_ENDPOINTS"] = endpoints
    from ops import ops_api as appmod

    importlib.reload(appmod)
    return TestClient(appmod.app)


@pytest.mark.asyncio
async def test_exposure_aggregates_binance_and_ibkr(monkeypatch):
    """Test the new comprehensive exposure aggregator"""
    # Mock engine endpoints
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://e_bin:8003,http://e_ibkr:8005")
    monkeypatch.setenv("OPS_IBKR_TICKERS", "AAPL,MSFT")

    # Mock Binance portfolio (BTC position)
    bin_port = {
        "positions": [
            {
                "symbol": "BTCUSDT.BINANCE",
                "qty_base": 0.002,
                "last_price_quote": 50000.0,
            }
        ]
    }
    # Mock IBKR portfolio (AAPL shares, no price in portfolio)
    ibkr_port = {"positions": [{"symbol": "AAPL.IBKR", "qty_base": 2.0}]}

    with respx.mock:
        respx.get("http://e_bin:8003/portfolio").mock(return_value=Response(200, json=bin_port))
        respx.get("http://e_ibkr:8005/portfolio").mock(return_value=Response(200, json=ibkr_port))

        # Provide IBKR price via fake module
        class FakeGauge:
            def __init__(self, v):
                self._v = v

            class _Val:
                def __init__(self, v):
                    self._v = v

                def get(self):
                    return self._v

            @property
            def _value(self):
                return FakeGauge._Val(self._v)

        class FakePrices:
            PRICE_METRICS = {"AAPL": FakeGauge(200.0), "MSFT": FakeGauge(410.0)}

        import sys

        sys.modules["ops.ibkr_prices"] = FakePrices()

        agg = await aggregate_exposure(
            engine_endpoints_env="http://e_bin:8003,http://e_ibkr:8005",
            include_watchlist_env="AAPL,MSFT",
        )
        # BTC exposure: 0.002 * 50_000 = 100
        # AAPL exposure: 2 * 200 = 400
        # MSFT exposure: 0 (no position) * 410 = 0
        assert round(agg.totals["exposure_usd"], 2) == 500.00  # BTC + AAPL
        assert "BTCUSDT.BINANCE" in agg.by_symbol
        assert "AAPL.IBKR" in agg.by_symbol
        assert "MSFT.IBKR" in agg.by_symbol

        # Verify positions
        btc_pos = agg.by_symbol["BTCUSDT.BINANCE"]
        assert btc_pos["qty_base"] == 0.002
        assert btc_pos["last_price_usd"] == 50000.0
        assert btc_pos["exposure_usd"] == 100.0

        aapl_pos = agg.by_symbol["AAPL.IBKR"]
        assert aapl_pos["qty_base"] == 2.0
        assert aapl_pos["last_price_usd"] == 200.0
        assert aapl_pos["exposure_usd"] == 400.0

        msft_pos = agg.by_symbol["MSFT.IBKR"]
        assert msft_pos["qty_base"] == 0.0
        assert msft_pos["last_price_usd"] == 410.0
        assert msft_pos["exposure_usd"] == 0.0

        # Check totals
        assert agg.totals["count"] == 3
        assert agg.totals["venues"] == 2  # Two different venue endpoints


@pytest.mark.asyncio
async def test_exposure_handles_unavailable_engines():
    """Test aggregator resilience with unavailable engines"""
    missing_portfolio = {
        "positions": [{"symbol": "ETHUSDT.BINANCE", "qty_base": 1.0, "last_price_quote": 2500.0}]
    }

    with respx.mock:
        # One engine available, one unavailable
        respx.get("http://good:8003/portfolio").mock(
            return_value=Response(200, json=missing_portfolio)
        )
        respx.get("http://bad:8004/portfolio").mock(return_value=Response(500, text="unavailable"))

        agg = await aggregate_exposure(engine_endpoints_env="http://good:8003,http://bad:8004")

        assert "ETHUSDT.BINANCE" in agg.by_symbol
        eth_pos = agg.by_symbol["ETHUSDT.BINANCE"]
        assert eth_pos["qty_base"] == 1.0
        assert eth_pos["last_price_usd"] == 2500.0
        assert eth_pos["exposure_usd"] == 2500.0
        assert agg.totals["count"] == 1


@respx.mock
def test_exposure_api_endpoint_integration(monkeypatch):
    """Test the OPS API endpoint that uses the aggregator"""
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://e_bin:8003")
    monkeypatch.setenv("OPS_IBKR_TICKERS", "")

    c = mk_client("http://e_bin:8003")

    # Mock Binance portfolio
    respx.get("http://e_bin:8003/portfolio").mock(
        return_value=Response(
            200,
            json={
                "positions": [
                    {
                        "symbol": "BTCUSDT.BINANCE",
                        "qty_base": 0.001,
                        "last_price_quote": 60000.0,
                    }
                ]
            },
        )
    )

    r = c.get("/aggregate/exposure")
    assert r.status_code == 200
    js = r.json()

    # Check structure matches new aggregator format
    assert "totals" in js
    assert "by_symbol" in js
    assert js["totals"]["exposure_usd"] == 60.0  # 0.001 * 60000
    assert "BTCUSDT.BINANCE" in js["by_symbol"]
