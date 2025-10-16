from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()
_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)


async def publish(evt):
    await _queue.put(evt)


@router.get("/events/stream")
async def stream():
    async def gen():
        while True:
            evt = await _queue.get()
            yield f"data: {json.dumps(evt)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

