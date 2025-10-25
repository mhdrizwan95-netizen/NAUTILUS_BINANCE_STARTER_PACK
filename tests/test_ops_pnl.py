import os, importlib, asyncio, contextlib
import pytest
import respx
from httpx import Response
from fastapi.testclient import TestClient
from ops.pnl_collector import pnl_collector_loop, PNL_REALIZED, PNL_UNREALIZED
from ops.pnl_collector import _venue_label

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
async def test_pnl_collector_gathers(monkeypatch):
    """Test that PnL collector aggregates data from multiple engines"""
    # Mock engine endpoints
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://engine_binance:8003,http://engine_ibkr:8005")

    # Mock responses with PnL data
    binance_pnl = {"pnl": {"realized": 134.2, "unrealized": 5.8}}
    ibkr_pnl = {"pnl": {"realized": 12.7, "unrealized": 0.1}}

    with respx.mock:
        respx.get("http://engine_binance:8003/account_snapshot").mock(return_value=Response(200, json=binance_pnl))
        respx.get("http://engine_ibkr:8005/account_snapshot").mock(return_value=Response(200, json=ibkr_pnl))

        # Run collector once (we'll cancel it after short run)
        task = asyncio.create_task(pnl_collector_loop())
        await asyncio.sleep(1)  # Let it run one cycle
        task.cancel()

        # Check that metrics were updated
        # Note: Prometheus Gauges use labels, so we need to access with labels
        binance_realized = PNL_REALIZED.labels(venue="ENGINE_BINANCE")
        binance_unrealized = PNL_UNREALIZED.labels(venue="ENGINE_BINANCE")
        ibkr_unrealized = PNL_UNREALIZED.labels(venue="ENGINE_IBKR")

        # Verify values were captured
        assert binance_realized._value.get() == 134.2
        assert binance_unrealized._value.get() == 5.8
        assert ibkr_unrealized._value.get() == 0.1

@pytest.mark.asyncio
async def test_pnl_collector_handles_engine_failures():
    """Test collector resilience when engines are unavailable"""
    with respx.mock:
        # Only one engine available
        respx.get("http://engine_binance:8003/account_snapshot").mock(
            return_value=Response(200, json={"pnl": {"realized": 100.0, "unrealized": 10.0}})
        )
        respx.get("http://engine_down:8004/account_snapshot").mock(return_value=Response(500, text="unavailable"))

        task = asyncio.create_task(pnl_collector_loop())
        await asyncio.sleep(1)
        task.cancel()

        # Check that available engine data was processed
        binance_realized = PNL_REALIZED.labels(venue="ENGINE_BINANCE")
        assert binance_realized._value.get() == 100.0

@respx.mock
def test_pnl_api_endpoint(monkeypatch):
    """Test that the /aggregate/pnl API endpoint returns aggregated PnL data"""
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://engine_binance:8003")

    c = mk_client("http://engine_binance:8003")

    # Mock the account snapshot endpoint for API test
    respx.get("http://engine_binance:8003/account_snapshot").mock(
        return_value=Response(200, json={"pnl": {"realized": 250.5, "unrealized": 15.3}})
    )

    # Update the metrics first
    async def _run_once():
        task = asyncio.create_task(pnl_collector_loop())
        await asyncio.sleep(1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run_once())

    # Now test the API endpoint
    r = c.get("/aggregate/pnl")
    assert r.status_code == 200

    data = r.json()
    assert "realized" in data
    assert "unrealized" in data

    # Check that the metrics are returned
    binance_venue = "ENGINE_BINANCE"
    assert binance_venue in data["realized"]
    assert binance_venue in data["unrealized"]
    assert abs(data["realized"][binance_venue] - 250.5) < 0.01
    assert abs(data["unrealized"][binance_venue] - 15.3) < 0.01

def test_pnl_venue_name_extraction():
    """Test that venue names are correctly extracted from engine URLs"""
    # This is tested implicitly in the main test, but we can verify the logic
    from ops.pnl_collector import _fetch_pnl

    # Test URL parsing logic (venue derivation)
    test_venue_urls = [
        ("http://engine_binance:8003", "ENGINE_BINANCE"),
        ("http://engine_ibkr:8005", "ENGINE_IBKR"),
        ("http://localhost:8765", "LOCALHOST"),
        ("https://prod-trader:443", "PROD-TRADER"),
    ]

    for url, expected_venue in test_venue_urls:
        assert _venue_label(url) == expected_venue
