import os
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

OPS_TOKEN = os.getenv("OPS_API_TOKEN", "test-ops-token-1234567890")
OPS_APPROVER_TOKEN = (
    (os.getenv("OPS_APPROVER_TOKENS") or "test-approver-token-1234567890").split(",")[0].strip()
)


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
    key = f"test-{uuid.uuid4()}"
    start = client.post(
        "/api/backtests",
        json={
            "strategyId": "trend_core",
            "startDate": "2024-01-01T00:00:00Z",
            "endDate": "2024-01-02T00:00:00Z",
        },
        headers={
            "X-Ops-Token": OPS_TOKEN,
            "X-Ops-Approver": OPS_APPROVER_TOKEN,
            "Idempotency-Key": key,
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


def test_backtest_requires_idempotency_key(client: TestClient) -> None:
    resp = client.post(
        "/api/backtests",
        json={"strategyId": "trend_core"},
        headers={"X-Ops-Token": OPS_TOKEN, "X-Ops-Approver": OPS_APPROVER_TOKEN},
    )
    assert resp.status_code == 400
    assert "Idempotency-Key" in resp.json().get("detail", "")


def test_backtest_replay_returns_cached_job_id(client: TestClient) -> None:
    idem = f"test-{uuid.uuid4()}"
    headers = {
        "X-Ops-Token": OPS_TOKEN,
        "X-Ops-Approver": OPS_APPROVER_TOKEN,
        "Idempotency-Key": idem,
    }
    payload = {
        "strategyId": "trend_core",
        "startDate": "2024-01-01T00:00:00Z",
        "endDate": "2024-01-02T00:00:00Z",
    }
    first = client.post("/api/backtests", json=payload, headers=headers)
    assert first.status_code == 200
    second = client.post("/api/backtests", json=payload, headers=headers)
    assert second.status_code == 200
    assert first.json() == second.json()
