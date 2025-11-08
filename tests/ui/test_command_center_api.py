import os
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ops import ui_api, ui_state
from ops.ui_services import OrdersService, PortfolioService

OPS_TOKEN = os.getenv("OPS_API_TOKEN", "test-ops-token-1234567890")


@pytest.fixture()
def client() -> TestClient:
    from ops import ops_api as appmod

    return TestClient(appmod.app)


def test_strategies_expose_param_schema(client: TestClient) -> None:
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "data" in payload
    assert "page" in payload
    items = payload["data"]
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
        headers={"X-Ops-Token": OPS_TOKEN, "Idempotency-Key": key},
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
        headers={"X-Ops-Token": OPS_TOKEN},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "idempotency.missing_header"


def test_backtest_replay_returns_cached_job_id(client: TestClient) -> None:
    idem = f"test-{uuid.uuid4()}"
    headers = {
        "X-Ops-Token": OPS_TOKEN,
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


def test_trades_recent_returns_paginated_envelope(client: TestClient) -> None:
    from ops import ui_api

    original = list(ui_api.RECENT_TRADES)
    try:
        ui_api.RECENT_TRADES.clear()
        now = int(time.time())
        for idx in range(5):
            ui_api.RECENT_TRADES.append(
                {
                    "time": now - idx * 60,
                    "symbol": f"SYM{idx}",
                    "side": "buy" if idx % 2 == 0 else "sell",
                    "qty": 1 + idx,
                    "price": 100 + idx,
                    "pnl": idx * 1.5,
                }
            )

        resp = client.get("/api/trades/recent?limit=2")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["page"]["limit"] == 2
        assert len(payload["data"]) == 2
        next_cursor = payload["page"]["nextCursor"]
        assert next_cursor

        resp_next = client.get(f"/api/trades/recent?cursor={next_cursor}")
        assert resp_next.status_code == 200
        payload_next = resp_next.json()
        assert isinstance(payload_next["data"], list)
        assert payload_next["data"]
    finally:
        ui_api.RECENT_TRADES.clear()
        ui_api.RECENT_TRADES.extend(original)


def test_alerts_returns_paginated_envelope(client: TestClient) -> None:
    from ops import ui_api

    original = list(ui_api.ALERTS_FEED)
    try:
        ui_api.ALERTS_FEED.clear()
        now = int(time.time())
        for idx in range(4):
            ui_api.ALERTS_FEED.append(
                {
                    "time": now - idx * 30,
                    "level": "info",
                    "text": f"Alert {idx}",
                }
            )

        resp = client.get("/api/alerts?limit=2")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["page"]["limit"] == 2
        assert len(payload["data"]) == 2
        assert payload["page"]["nextCursor"]
    finally:
        ui_api.ALERTS_FEED.clear()
        ui_api.ALERTS_FEED.extend(original)


def test_strategy_patch_enforces_idempotency(client: TestClient) -> None:
    class _StubStrategyService:
        async def patch(self, strategy_id: str, updates: dict[str, Any]) -> dict[str, Any]:
            return {"strategyId": strategy_id, "applied": updates}

    original_strategy = ui_state.get_service("strategy")
    ui_state.configure(strategy=_StubStrategyService())
    try:
        resp_missing = client.patch(
            "/api/strategies/demo-strategy",
            json={"enabled": True},
            headers={"X-Ops-Token": OPS_TOKEN},
        )
        assert resp_missing.status_code == 400

        idem = f"test-{uuid.uuid4()}"
        headers = {
            "X-Ops-Token": OPS_TOKEN,
            "X-Ops-Actor": "auditor",
            "Idempotency-Key": idem,
        }
        resp = client.patch(
            "/api/strategies/demo-strategy",
            json={"enabled": True},
            headers=headers,
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload == {"strategyId": "demo-strategy", "applied": {"enabled": True}}

        replay = client.patch(
            "/api/strategies/demo-strategy",
            json={"enabled": True},
            headers=headers,
        )
        assert replay.status_code == 200
        assert replay.json() == payload
    finally:
        ui_state.configure(strategy=original_strategy)


def test_account_transfer_enforces_idempotency(client: TestClient) -> None:
    transfer_payload = {
        "asset": "USDT",
        "amount": 25.0,
        "source": "spot",
        "target": "margin",
    }
    resp_missing = client.post(
        "/api/account/transfer",
        json=transfer_payload,
        headers={"X-Ops-Token": OPS_TOKEN},
    )
    assert resp_missing.status_code == 400

    idem = f"test-{uuid.uuid4()}"
    headers = {
        "X-Ops-Token": OPS_TOKEN,
        "X-Ops-Actor": "auditor",
        "Idempotency-Key": idem,
    }
    resp = client.post(
        "/api/account/transfer",
        json=transfer_payload,
        headers=headers,
    )
    assert resp.status_code == 200
    first_payload = resp.json()
    assert first_payload["ok"] is True
    repeat = client.post(
        "/api/account/transfer",
        json=transfer_payload,
        headers=headers,
    )
    assert repeat.status_code == 200
    assert repeat.json() == first_payload


def test_ws_session_requires_actor(client: TestClient) -> None:
    resp_missing = client.post(
        "/api/ops/ws-session",
        headers={"X-Ops-Token": OPS_TOKEN},
    )
    assert resp_missing.status_code == 400
    body = resp_missing.json()
    assert body["error"]["code"] == "auth.actor_required"

    resp = client.post(
        "/api/ops/ws-session",
        headers={"X-Ops-Token": OPS_TOKEN, "X-Ops-Actor": "observer"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "session" in payload and "expires" in payload


def test_orders_open_returns_paginated_envelope(client: TestClient) -> None:
    temp_orders = OrdersService()
    original_orders = ui_state.get_services()["orders"]
    ui_state.configure(orders=temp_orders)
    temp_orders.update_orders(
        [
            {
                "id": "order-1",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "qty": 1.0,
                "price": 42000.0,
                "status": "OPEN",
                "createdAt": int(time.time() * 1000),
            },
            {
                "id": "order-2",
                "symbol": "ETHUSDT",
                "side": "SELL",
                "type": "LIMIT",
                "qty": 2.0,
                "price": 3200.0,
                "status": "OPEN",
                "createdAt": int(time.time() * 1000) - 1000,
            },
        ]
    )
    try:
        resp = client.get("/api/orders/open?limit=1")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["page"]["limit"] == 1
        assert len(payload["data"]) == 1
        assert payload["page"]["nextCursor"]
    finally:
        temp_orders.update_orders([])
        ui_state.configure(orders=original_orders)


def test_positions_open_returns_paginated_envelope(client: TestClient) -> None:
    temp_portfolio = PortfolioService()
    original_portfolio = ui_state.get_services()["portfolio"]
    ui_state.configure(portfolio=temp_portfolio)
    temp_portfolio.update_snapshot(
        {
            "equity": 0.0,
            "cash": 0.0,
            "exposure": 0.0,
            "pnl": {"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
            "positions": [
                {
                    "id": "pos-1",
                    "symbol": "BTCUSDT",
                    "qty": 0.5,
                    "entry": 40000,
                    "mark": 40500,
                    "pnl": 250,
                },
                {
                    "id": "pos-2",
                    "symbol": "ETHUSDT",
                    "qty": 1.5,
                    "entry": 2800,
                    "mark": 2750,
                    "pnl": -75,
                },
            ],
            "ts": time.time(),
            "source": "test",
        }
    )
    try:
        resp = client.get("/api/positions/open?limit=1")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["page"]["limit"] == 1
        assert len(payload["data"]) == 1
        assert payload["page"]["nextCursor"]
    finally:
        temp_portfolio.update_snapshot(
            {
                "equity": 0.0,
                "cash": 0.0,
                "exposure": 0.0,
                "pnl": {"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
                "positions": [],
                "ts": time.time(),
                "source": "test",
            }
        )
        ui_state.configure(portfolio=original_portfolio)


def test_strategies_governance_returns_paginated_envelope(client: TestClient) -> None:
    class _StubStrategyService:
        async def list(self) -> dict[str, Any]:
            return {
                "current": "alpha",
                "strategies": [
                    {"id": "alpha", "weight": 0.7, "enabled": True, "is_current": True},
                    {"id": "beta", "weight": 0.3, "enabled": True, "is_current": False},
                ],
                "updated_at": 123.0,
            }

    original_strategy = ui_state.get_service("strategy")
    ui_state.configure(strategy=_StubStrategyService())
    try:
        resp = client.get("/api/strategies/governance?limit=1")
        assert resp.status_code == 200
        payload = resp.json()
        assert len(payload["data"]) == 1
        assert payload["meta"]["current"] == "alpha"
        assert payload["page"]["nextCursor"]
    finally:
        ui_state.configure(strategy=original_strategy)


def test_metrics_models_returns_paginated_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_collect(
        _state: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        models = [
            {
                "id": "trend:binance",
                "model": "trend",
                "venue": "binance",
                "orders_submitted_total": 10,
                "orders_filled_total": 8,
                "trades": 8,
                "pnl_realized_total": 125.0,
                "pnl_unrealized_total": 45.0,
                "total_pnl": 170.0,
                "win_rate": 0.6,
                "return_pct": 4.2,
                "sharpe": 1.1,
                "drawdown": 0.08,
                "max_drawdown": 0.12,
                "strategy_type": "momentum",
                "version": "1.0",
                "trading_days": 12,
            },
            {
                "id": "scalp:binance",
                "model": "scalp",
                "venue": "binance",
                "orders_submitted_total": 5,
                "orders_filled_total": 5,
                "trades": 5,
                "pnl_realized_total": 55.0,
                "pnl_unrealized_total": 15.0,
                "total_pnl": 70.0,
                "win_rate": 0.7,
                "return_pct": 2.1,
                "sharpe": 0.9,
                "drawdown": 0.05,
                "max_drawdown": 0.09,
                "strategy_type": "scalp",
                "version": "1.1",
                "trading_days": 7,
            },
        ]
        meta = {"metricsSource": "stub", "records": len(models), "fetchedAt": time.time()}
        return models, {"positions": []}, meta

    monkeypatch.setattr(ui_api, "_collect_metrics_bundle", _fake_collect)

    resp = client.get("/api/metrics/models?limit=1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["page"]["limit"] == 1
    assert len(payload["data"]) == 1
    assert payload["meta"]["metricsSource"] == "stub"
    assert payload["page"]["nextCursor"]
