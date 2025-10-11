import os, importlib
import pytest
import respx
from httpx import Response
from fastapi.testclient import TestClient
from ops.portfolio_collector import portfolio_collector_loop, PORTFOLIO_EQUITY, PORTFOLIO_GAIN, PORTFOLIO_RET

@pytest.fixture(autouse=True)
def _env_clear(monkeypatch):
    if "ENGINE_ENDPOINTS" in os.environ:
        monkeypatch.delenv("ENGINE_ENDPOINTS", raising=False)

def mk_client(endpoints: str):
    os.environ["ENGINE_ENDPOINTS"] = endpoints
    from ops import ops_api as appmod
    importlib.reload(appmod)
    return TestClient(appmod.app)

@pytest.mark.asyncio
async def test_portfolio_collector_sums_and_returns(monkeypatch):
    """Test portfolio collector sums equity/cash and computes returns with baseline logic"""
    # Mock engine endpoints
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://engine_binance:8003,http://engine_ibkr:8005")

    # Mock account snapshots
    snap1 = {"equity_usd": 1000.0, "cash_usd": 800.0, "pnl": {"unrealized": 5.0}, "positions": []}
    snap2 = {"equity_usd": 500.0, "cash_usd": 500.0, "pnl": {"unrealized": 0.0}, "positions": []}

    with respx.mock:
        respx.get("http://engine_binance:8003/account_snapshot").mock(return_value=Response(200, json=snap1))
        respx.get("http://engine_ibkr:8005/account_snapshot").mock(return_value=Response(200, json=snap2))

        # Run collector once (cancel after short run)
        task = asyncio.create_task(portfolio_collector_loop(interval_sec=1))
        await asyncio.sleep(1.5)  # Let one iteration run
        task.cancel()

    # Check aggregated values
    total_equity = PORTFOLIO_EQUITY._value.get()
    total_cash = float(800.0 + 500.0)  # cash from both engines

    # First iteration sets baseline ≈ total equity → zero/small gain
    assert total_equity == 1500.0  # 1000 + 500
    assert abs(PORTFOLIO_GAIN._value.get()) < 1e-6  # gain ~0 on baseline init
    assert abs(PORTFOLIO_RET._value.get()) < 1e-6   # return % ~0

@pytest.mark.asyncio
async def test_portfolio_collector_handlesUnavailable_engines():
    """Test collector resilience when engines are unavailable"""
    with respx.mock:
        available_snap = {"equity_usd": 1000.0, "cash_usd": 800.0, "pnl": {"unrealized": 5.0}, "positions": []}
        respx.get("http://engine_binance:8003/account_snapshot").mock(return_value=Response(200, json=available_snap))
        respx.get("http://engine_down:8004/account_snapshot").mock(return_value=Response(500, text="unavailable"))

        task = asyncio.create_task(portfolio_collector_loop(interval_sec=1))
        await asyncio.sleep(1.5)
        task.cancel()

        # Should only count available engine data
        assert PORTFOLIO_EQUITY._value.get() == 1000.0
        assert abs(PORTFOLIO_GAIN._value.get()) < 1e-6  # baseline set on first run

@respx.mock
def test_portfolio_api_endpoint(monkeypatch):
    """Test that /aggregate/portfolio endpoint returns portfolio snapshot"""
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://engine_binance:8003")

    c = mk_client("http://engine_binance:8003")

    # Mock snapshot for API test
    respx.get("http://engine_binance:8003/account_snapshot").mock(
        return_value=Response(200, json={
            "equity_usd": 1234.56,
            "cash_usd": 789.12,
            "pnl": {"unrealized": 12.34},
            "positions": []
        })
    )

    # Update metrics first
    task = asyncio.create_task(portfolio_collector_loop(interval_sec=1))
    import asyncio as asyncio_module
    asyncio_module.run(asyncio_module.sleep(1.5))
    task.cancel()

    # Test API endpoint
    r = c.get("/aggregate/portfolio")
    assert r.status_code == 200

    data = r.json()
    # Should return structured data with calculated metrics
    assert abs(data["equity_usd"] - 1234.56) < 0.01
    assert abs(data["cash_usd"] - 789.12) < 0.01
    assert abs(data["gain_usd"]) < 1e-6  # 0 or very small on first run
    assert abs(data["return_pct"]) < 1e-6  # 0 or very small on first run
    assert "baseline_equity_usd" in data
    assert "last_refresh_epoch" in data

def test_portfolio_collector_venue_extraction():
    """Test venue name extraction from URLs"""
    from ops.portfolio_collector import _fetch_pnl  # Can reuse similar logic

    # Test URL parsing (similar to pnl collector)
    test_urls = [
        ("http://engine_binance:8003", "ENGINE_BINANCE"),
        ("http://engine_ibkr:8005", "ENGINE_IBKR"),
        ("http://localhost:8765", "LOCALHOST"),
    ]

    # The venue extraction logic in portfolio collector is similar
    for url, expected_venue in test_urls:
        venue_clean = url.split("//")[-1].split(":")[0].replace("engine_", "").upper()
        assert venue_clean == expected_venue
