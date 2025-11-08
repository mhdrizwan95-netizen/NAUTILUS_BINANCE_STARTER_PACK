import importlib
import os

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response


@pytest.fixture(autouse=True)
def _env_isolation(monkeypatch):
    for k in ["ENGINE_ENDPOINTS"]:
        if k in os.environ:
            monkeypatch.delenv(k, raising=False)


def mk_client(endpoints: str):
    os.environ["ENGINE_ENDPOINTS"] = endpoints
    from ops import ops_api as appmod

    importlib.reload(appmod)
    return TestClient(appmod.app)


@respx.mock
def test_aggregate_health_happy_path():
    c = mk_client("http://e1:8003,http://e2:8004")
    respx.get("http://e1:8003/health").mock(
        return_value=Response(200, json={"engine": "ok", "equity": 100})
    )
    respx.get("http://e2:8004/health").mock(
        return_value=Response(200, json={"engine": "ok", "equity": 200})
    )
    r = c.get("/aggregate/health")
    assert r.status_code == 200
    js = r.json()
    assert len(js["venues"]) == 2
    assert js["venues"][0]["engine"] == "ok"


@respx.mock
def test_aggregate_portfolio_sums_equity_and_ignores_bad():
    c = mk_client("http://e1:8003,http://e2:8004,http://e3:8005")
    # Good engines
    respx.get("http://e1:8003/portfolio").mock(
        return_value=Response(200, json={"equity_usd": 123.45})
    )
    respx.get("http://e2:8004/portfolio").mock(return_value=Response(200, json={"equity_usd": 200}))
    # Bad engine (down or invalid JSON)
    respx.get("http://e3:8005/portfolio").mock(return_value=Response(500, text="oops"))
    r = c.get("/aggregate/portfolio")
    assert r.status_code == 200
    js = r.json()
    assert pytest.approx(js["total_equity_usd"], rel=1e-6) == 323.45
    assert js["count"] == 2  # only two valid venues included


@respx.mock
def test_aggregate_portfolio_handles_missing_equity():
    c = mk_client("http://e1:8003,http://e2:8004")
    # Missing equity field
    respx.get("http://e1:8003/portfolio").mock(return_value=Response(200, json={"cash": 50.0}))
    # None equity field
    respx.get("http://e2:8004/portfolio").mock(
        return_value=Response(200, json={"equity_usd": None})
    )
    r = c.get("/aggregate/portfolio")
    assert r.status_code == 200
    js = r.json()
    assert js["total_equity_usd"] == 0.0
    assert js["count"] == 2  # both responses valid but equity is 0


@respx.mock
def test_aggregate_metrics_collects_from_all_venues():
    c = mk_client("http://e1:8003,http://e2:8004")
    respx.get("http://e1:8003/metrics").mock(
        return_value=Response(200, json={"orders_submitted": 10, "orders_rejected": 1})
    )
    respx.get("http://e2:8004/metrics").mock(
        return_value=Response(200, json={"orders_submitted": 15, "orders_rejected": 0})
    )
    r = c.get("/aggregate/metrics")
    assert r.status_code == 200
    js = r.json()
    assert len(js["venues"]) == 2
    assert js["venues"][0]["orders_submitted"] == 10
    assert js["venues"][1]["orders_submitted"] == 15


@respx.mock
def test_aggregate_defaults_when_env_missing():
    # No ENGINE_ENDPOINTS env → should fall back to defaults inside module
    from ops import ops_api as appmod

    importlib.reload(appmod)
    c = TestClient(appmod.app)
    # Mock defaults
    respx.get("http://engine_binance:8003/health").mock(
        return_value=Response(200, json={"engine": "ok"})
    )
    r = c.get("/aggregate/health")
    assert r.status_code == 200
    assert len(r.json()["venues"]) == 1


@respx.mock
def test_partial_failure_isolation():
    c = mk_client("http://e1:8003,http://e2:8004,http://e3:8005")
    # One success, one empty, one error
    respx.get("http://e1:8003/health").mock(
        return_value=Response(200, json={"engine": "ok", "venue": "binance"})
    )
    respx.get("http://e2:8004/health").mock(return_value=Response(200, json={}))  # empty but 200 OK
    respx.get("http://e3:8005/health").mock(side_effect=Exception("connection failed"))
    r = c.get("/aggregate/health")
    assert r.status_code == 200
    js = r.json()
    assert len(js["venues"]) == 3  # all positions preserved
    assert js["venues"][0]["engine"] == "ok"
    assert js["venues"][1] == {}  # empty response passed through
    assert js["venues"][2] == {}  # exception converted to empty dict
