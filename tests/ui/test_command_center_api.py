import time
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    from ops import ops_api as appmod
    return TestClient(appmod.app)


def test_strategies_expose_param_schema(client: TestClient) -> None:
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    first = items[0]
    # Schema-driven contract must be present
    assert "paramsSchema" in first
    schema = first["paramsSchema"]
    assert isinstance(schema, dict)
    assert "fields" in schema
    assert isinstance(schema["fields"], list)


def test_backtest_job_runner_returns_result(client: TestClient) -> None:
    # Start a synthetic backtest and poll for completion
    start = client.post(
        "/api/backtests",
        json={
            "strategyId": "trend_core",
            "startDate": "2024-01-01T00:00:00Z",
            "endDate": "2024-01-02T00:00:00Z",
        },
    )
    assert start.status_code == 200
    job_id = start.json().get("jobId")
    assert job_id

    deadline = time.time() + 15.0
    result: dict[str, Any] | None = None
    while time.time() < deadline:
        poll = client.get(f"/api/backtests/{job_id}")
        assert poll.status_code == 200
        payload = poll.json()
        if payload.get("status") == "done" and payload.get("result"):
            result = payload["result"]
            break
        time.sleep(0.5)

    assert result is not None, "backtest did not complete in time"
    # Minimal shape checks
    metrics = result.get("metrics")
    assert isinstance(metrics, dict)
    assert "totalReturn" in metrics
    assert "equityCurve" in result
    assert isinstance(result["equityCurve"], list)
