import os, importlib, json
import pytest
import respx
from httpx import Response
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def _env_clear(monkeypatch):
    if "ENGINE_ENDPOINTS" in os.environ:
        monkeypatch.delenv("ENGINE_ENDPOINTS", raising=False)
    if "ALERT_WEBHOOK_URL" in os.environ:
        monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)

def mk_client(endpoints: str):
    os.environ["ENGINE_ENDPOINTS"] = endpoints
    from ops import ops_api as appmod
    importlib.reload(appmod)
    return TestClient(appmod.app)

@respx.mock
def test_risk_alerts_on_high_exposure():
    """Test that risk monitoring triggers alerts when exposure exceeds limit."""
    c = mk_client("http://e1:8003")

    # Mock exposure response with high BTCUSDT position
    respx.get("http://localhost:8001/aggregate/exposure").mock(
        return_value=Response(200, json={
            "total_exposure_usd": 1500.0,
            "count": 1,
            "items": [{
                "symbol": "BTCUSDT",
                "qty_base": 0.05,
                "mark": 50000.0,
                "value_usd": 2500.0,  # Above default limit of 1000
                "is_dust": False
            }],
            "dust_threshold_usd": 2.0
        })
    )

    # Mock webhook endpoint (if configured)
    webhook_mock = respx.post("https://hooks.slack.com/your-webhook-here").mock(
        return_value=Response(200, json={"ok": True})
    )

    os.environ["ALERT_WEBHOOK_URL"] = "https://hooks.slack.com/your-webhook-here"

    from ops import ops_api
    importlib.reload(ops_api)

    # Simulate the risk monitoring loop (one iteration)
    import asyncio
    async def test_monitor():
        await ops_api._risk_monitoring_loop()

    asyncio.run(test_monitor())

    # Check webhook was called
    assert webhook_mock.call_count == 1
    call_data = json.loads(webhook_mock.calls[0].request.content)
    assert "RISK LIMIT BREACH: BTCUSDT" in call_data["text"]
    assert "2500.00 > $1000" in call_data["text"]

@respx.mock
def test_no_alert_on_safe_exposure():
    """Test that alerts are not sent when exposure is within limits."""
    c = mk_client("http://e1:8003")

    # Mock exposure response with safe position
    respx.get("http://localhost:8001/aggregate/exposure").mock(
        return_value=Response(200, json={
            "total_exposure_usd": 750.0,
            "count": 1,
            "items": [{
                "symbol": "BTCUSDT",
                "qty_base": 0.03,
                "mark": 25000.0,
                "value_usd": 750.0,  # Below limit of 1000
                "is_dust": False
            }],
            "dust_threshold_usd": 2.0
        })
    )

    # Mock webhook endpoint
    webhook_mock = respx.post("https://hooks.slack.com/no-actual").mock(
        return_value=Response(200, json={"ok": True})
    )

    from ops import ops_api
    importlib.reload(ops_api)

    # Simulate the risk monitoring loop
    import asyncio
    async def test_monitor():
        await ops_api._risk_monitoring_loop()

    asyncio.run(test_monitor())

    # Check webhook was NOT called
    assert webhook_mock.call_count == 0

@respx.mock
def test_risk_monitor_handles_monitor_errors():
    """Test risk monitoring continues despite errors in one iteration."""
    c = mk_client("http://e1:8003")

    # Mock failure response
    respx.get("http://localhost:8001/aggregate/exposure").mock(
        return_value=Response(500, text="Service down")
    )

    from ops import ops_api
    importlib.reload(ops_api)

    # Simulate the risk monitoring loop - should not raise exception
    import asyncio
    async def test_monitor():
        await ops_api._risk_monitoring_loop()

    # Should complete without errors (logged internally)
    asyncio.run(test_monitor())
