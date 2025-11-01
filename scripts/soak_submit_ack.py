#!/usr/bin/env python3
import time, requests, json

ENGINE = "http://localhost:8003"

for i in range(50):
    payload = {"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 5}
    t0 = time.time()
    r = requests.post(
        f"{ENGINE}/orders/market",
        headers={"content-type": "application/json"},
        data=json.dumps(payload),
    )
    dt = (time.time() - t0) * 1000
    print(f"{i:03d} status={r.status_code} dt_ms={dt:.1f}")
    time.sleep(0.2)

print("Check histogram: curl -s http://localhost:8003/metrics | grep submit_to_ack_ms")
