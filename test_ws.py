import asyncio
import websockets
import json

async def test_listen():
    uri = "ws://localhost:8003/ws"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected! Listening for messages...")
            while True:
                msg = await websocket.recv()
                data = json.loads(msg)
                if data.get("type") == "strategy.performance":
                    # print(f"RECEIVED PERF: {json.dumps(data, indent=2)}")
                    items = data.get("data", [])
                    for item in items:
                        print(f"RECEIVED TELEMETRY: ID={item.get('id')} PnL={item.get('performance', {}).get('pnl')}")
                        
                elif data.get("type") == "heartbeat":
                    pass
                    # print("Heartbeat...")
                # else:
                #    print(f"Received type: {data.get('type')}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_listen())
