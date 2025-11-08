import importlib
import os

import pytest
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


def test_trading_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TRADING_ENABLED", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("TRADE_SYMBOLS", "BTCUSDT")
    from engine.config import load_risk_config

    cfg = load_risk_config()
    assert cfg.trading_enabled is False


def test_disabled_trading_rejects_market_order():
    c = mk_client({"TRADING_ENABLED": "false", "TRADE_SYMBOLS": "BTCUSDT"})
    resp = c.post("/orders/market", json={"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 10})
    assert resp.status_code == 403
    j = resp.json()
    assert j["status"] == "rejected"
    assert j["error"] == "TRADING_DISABLED"


def test_min_notional_enforced():
    c = mk_client(
        {
            "TRADING_ENABLED": "true",
            "MIN_NOTIONAL_USDT": "7",
            "TRADE_SYMBOLS": "BTCUSDT",
        }
    )
    r = c.post("/orders/market", json={"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 5})
    assert r.status_code == 400
    assert r.json()["error"] == "NOTIONAL_TOO_SMALL"


def test_symbol_allowlist_blocks_others():
    c = mk_client({"TRADING_ENABLED": "true", "TRADE_SYMBOLS": "BTCUSDT,ETHUSDT"})
    r = c.post("/orders/market", json={"symbol": "BNBUSDT.BINANCE", "side": "BUY", "quote": 10})
    assert r.status_code == 403
    assert r.json()["error"] == "SYMBOL_NOT_ALLOWED"


def test_rate_limit_blocks_when_exceeded():
    # Rate limit is tricky to test without mocking asyncio, so we'll verify it exists
    import os

    from engine.config import load_risk_config
    from engine.risk import RiskRails

    os.environ["MAX_ORDERS_PER_MIN"] = "1"
    cfg = load_risk_config()
    rails = RiskRails(cfg)
    # First order should pass validation
    ok, _ = rails.check_order(symbol="BTCUSDT.BINANCE", side="BUY", quote=10.0, quantity=None)
    assert ok
    # Second should be rate limited (within ~1s)
    ok2, err = rails.check_order(symbol="BTCUSDT.BINANCE", side="BUY", quote=10.0, quantity=None)
    assert not ok2
    assert err["error"] == "ORDER_RATE_EXCEEDED"


def test_quantity_rejected_without_price(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADING_ENABLED", "true")
    monkeypatch.setenv("TRADE_SYMBOLS", "BTCUSDT")
    monkeypatch.setenv("MIN_NOTIONAL_USDT", "1")

    from engine.config import load_risk_config
    from engine.core import order_router
    from engine.risk import RiskRails

    cfg = load_risk_config()

    class DummyClient:
        def get_last_price(self, *_args, **_kwargs):
            return 0.0

    monkeypatch.setattr(order_router, "prices", lambda *_: 0.0, raising=False)
    monkeypatch.setattr(order_router, "exchange_client", lambda: DummyClient(), raising=False)
    monkeypatch.setattr(
        order_router, "portfolio_snapshot", lambda: {"positions": []}, raising=False
    )
    rails = RiskRails(cfg)

    ok, err = rails.check_order(symbol="BTCUSDT.BINANCE", side="BUY", quote=None, quantity=1.0)
    assert not ok
    assert err["error"] == "PRICE_UNAVAILABLE"
