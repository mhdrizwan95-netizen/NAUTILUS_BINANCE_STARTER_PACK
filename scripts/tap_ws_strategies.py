import asyncio
import websockets
import json
import os

# Connect with the token currently in use or bypassing it
TOKEN = "mfbAk5oc2p9ZVtQJQiSQDQWvINnnWzm-tzCwHErD1Sk" # From logs

async def listen():
    uri = f"ws://ops:8002/ws?token={TOKEN}"
    async with websockets.connect(uri) as websocket:
        print(f"Connected to {uri}")
        # Subscribe if needed (the engine pushes strategies by default usually, or we assume specific channel)
        # Based on app.py, it pushes automatically.
        while True:
            msg = await websocket.recv()
            print(f"RAW: {msg[:200]}...") # Print first 200 chars to avoid spam
            data = json.loads(msg)
            # Structure matches internal engine event?
            if "strategies" in data:
                 for s in data["strategies"]:
                     print(f"ID: {s.get('id')} | Sig: {s.get('signal')} | Feats: {type(s.get('metrics', {}).get('features'))}")
                     if s.get("id") == "hmm_ensemble":
                         print(f"Full HMM: {s}")

if __name__ == "__main__":
    try:
        asyncio.run(listen())
    except KeyboardInterrupt:
        pass
