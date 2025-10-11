import uuid
import os
import importlib
from fastapi.testclient import TestClient

def mk_client():
    from engine import app as appmod
    from engine.idempotency import CACHE
    importlib.reload(appmod)
    # Clear cache for clean tests
    CACHE.cache.clear()
    return TestClient(appmod.app)

def test_duplicate_idempotency_key_returns_same_response():
    os.makedirs("engine/logs", exist_ok=True)
    c = mk_client()
    key = str(uuid.uuid4())
    body = {"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 10}
    r1 = c.post("/orders/market", headers={"X-Idempotency-Key": key}, json=body)
    r2 = c.post("/orders/market", headers={"X-Idempotency-Key": key}, json=body)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["order"] == r2.json()["order"]

def test_order_log_and_retrieval():
    os.makedirs("engine/logs", exist_ok=True)
    # Clear log file
    log_path = "engine/logs/orders.jsonl"
    if os.path.exists(log_path):
        os.remove(log_path)

    c = mk_client()
    key = str(uuid.uuid4())
    r = c.post("/orders/market", headers={"X-Idempotency-Key": key}, json={"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 10})
    assert r.status_code == 200
    order_id = r.json()["order"]["id"]
    q = c.get(f"/orders/{order_id}")
    assert q.status_code == 200
    assert q.json()["order"]["id"] == order_id
