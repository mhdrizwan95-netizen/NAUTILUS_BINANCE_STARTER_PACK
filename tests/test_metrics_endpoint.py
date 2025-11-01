import os
import importlib
from fastapi.testclient import TestClient


def mk_client(env: dict[str, str]):
    # Set minimal required env vars for testing
    os.environ.setdefault("DEMO_API_KEY_SPOT", "test_key")
    os.environ.setdefault("DEMO_API_SECRET_SPOT", "test_secret")
    os.environ.update(env)
    # Reload to pick up env
    import engine.app as appmod

    importlib.reload(appmod)
    return TestClient(appmod.app)


def test_metrics_exposes_prometheus_text():
    c = mk_client({"TRADING_ENABLED": "true", "TRADE_SYMBOLS": "BTCUSDT"})
    r = c.get("/metrics")
    assert r.status_code == 200
    assert "orders_submitted_total" in r.text
    assert "orders_rejected_total" in r.text
    assert "fill_latency_ms" in r.text
    assert "pnl_realized_total" in r.text
    assert "pnl_unrealized_total" in r.text
    assert "equity_usd" in r.text
    assert "cash_usd" in r.text
    assert "exposure_usd" in r.text
