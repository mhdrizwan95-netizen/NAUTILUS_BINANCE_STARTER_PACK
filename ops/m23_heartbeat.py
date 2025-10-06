"""
M23 Heartbeat — Streams lineage + calibration status to Dashboard WS every 10 seconds.
Keeps dashboard tiles alive between scheduler/guardian events.
"""

import asyncio, os, json, glob, datetime, aiohttp

OPS_BASE = os.environ.get("OPS_BASE", "http://127.0.0.1:8001")  # ops_api service
DASH_BASE = os.environ.get("DASH_BASE", "http://127.0.0.1:8002")  # dashboard service


async def get_lineage_summary():
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"{OPS_BASE}/lineage", timeout=3) as r:
                if r.status == 200:
                    data = await r.json()
                    idx = data.get("index", {})
                    latest = idx.get("models", [{}])[-1] if idx.get("models") else {}
                    return {
                        "ok": True,
                        "count": len(idx.get("models", [])),
                        "latest": latest.get("tag", "unknown"),
                    }
    except Exception:
        pass
    return {"ok": False}


async def get_calibration_gallery():
    """List calibration PNGs for M15 gallery."""
    base = os.path.join("data", "processed", "calibration")
    files = sorted(glob.glob(os.path.join(base, "*.png")))
    recent = files[-3:] if files else []
    return {"ok": True, "files": [os.path.basename(f) for f in recent]}


async def broadcast(topic: str, payload: dict):
    """Send payload to dashboard WS topic."""
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(f"{DASH_BASE}/ws/{topic}") as ws:
                await ws.send_json(payload)
    except Exception:
        pass


async def heartbeat_loop():
    while True:
        ts = datetime.datetime.utcnow().isoformat()
        lineage = await get_lineage_summary()
        calibs = await get_calibration_gallery()
        payload = {"ts": ts, "lineage": lineage, "calibration": calibs}
        await broadcast("lineage", payload)
        await broadcast("calibration", payload)
        await asyncio.sleep(10)  # every 10s


if __name__ == "__main__":
    asyncio.run(heartbeat_loop())
