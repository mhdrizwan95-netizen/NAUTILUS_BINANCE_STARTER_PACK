import time

from fastapi.testclient import TestClient

from ops.ops_api import APP


def test_websocket_flow():
    client = TestClient(APP)

    # 1. Get Session
    headers = {"X-Ops-Actor": "test"}
    resp = client.post("/ops/ws-session", headers=headers)
    assert resp.status_code == 200, f"Failed to get session: {resp.text}"
    session = resp.json()["session"]
    print(f"Got session: {session}")

    # 2. Connect WS
    with client.websocket_connect(f"/ws?session={session}") as websocket:
        print("WebSocket Connected!")

        # 3. Subscribe
        sub_msg = {"type": "subscribe", "channels": ["prices", "metrics"]}
        websocket.send_json(sub_msg)
        print("Sent Subscribe")

        # 4. Inject Price Tick via HTTP
        print("Injecting Price Tick via HTTP...")
        tick = {"symbol": "BTCUSDT", "price": 50000.0, "time": time.time()}
        resp = client.post(
            "/events/price",
            json=tick,
            headers={"X-Ops-Token": "dev-token"},  # Ensure this matches env or default
        )
        assert resp.status_code == 200, f"Injection failed: {resp.text}"
        print("Injection Success")

        # 5. Verify Receipt
        # We might receive heartbeat or the price tick. Read loop.
        found = False
        for _ in range(3):
            try:
                data = websocket.receive_json()
                print(f"Received: {data}")
                if data.get("type") == "prices" and data["data"]["symbol"] == "BTCUSDT":
                    print("SUCCESS: Received injected price tick!")
                    found = True
                    break
            except Exception as e:
                print(f"Error receiving: {e}")
                break

        if not found:
            print("FAILURE: Did not receive injected price tick")
            exit(1)


if __name__ == "__main__":
    # Mock env vars if needed for the app to start correctly
    import os

    os.environ["OPS_API_TOKEN"] = "dev-token"
    test_websocket_flow()
