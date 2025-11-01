from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .models import Situation
from .store import SituationStore
from .matcher import Matcher


router = APIRouter()
_store = SituationStore()
_matcher = Matcher(_store)


@router.on_event("startup")
async def _boot():
    await _store.load()


@router.get("/situations")
def list_situations() -> Dict[str, Any]:
    return {"situations": [s.model_dump() for s in _store.list()]}


@router.post("/situations")
async def add_situation(sit_def: Dict[str, Any]):
    try:
        s = Situation(**sit_def)
    except Exception as e:
        raise HTTPException(400, f"invalid situation: {e}")
    await _store.add_or_update(s)
    return {"ok": True}


@router.patch("/situations/{name}")
async def patch_situation(name: str, patch: Dict[str, Any]):
    s = await _store.patch(name, patch)
    if not s:
        raise HTTPException(404, "not found")
    return {"ok": True}


@router.post("/situations/control/priorities")
async def update_priorities(body: Dict[str, Any]):
    ok = True
    for u in body.get("updates", []):
        ok = (
            await _store.update_priority(u.get("name"), float(u.get("priority", 0)))
        ) and ok
    return {"ok": ok}


@router.post("/situations/feedback/outcome")
async def post_feedback(body: Dict[str, Any]):
    # Placeholder: in production, persist and update online EV per situation
    # body: { event_id, pnl_usd, hold_sec, filled, ... }
    return {"ok": True}


@router.get("/situations/events/recent")
def recent_events(limit: int = 100) -> Dict[str, Any]:
    items = list(_matcher.recent)[-int(limit) :]
    return {"items": items}


@router.get("/situations/events/stream")
async def events_stream():
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _matcher.subscribers.append(q)

    async def gen():
        try:
            while True:
                evt = await q.get()
                yield f"data: {json.dumps(evt)}\n\n"
        finally:
            try:
                _matcher.subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/situations/ingest_bar")
async def ingest_bar(bar: Dict[str, Any]):
    # bar: { symbol, ts, feats{...} } (ts optional)
    symbol = bar.get("symbol")
    feats = bar.get("feats") or {}
    ts = bar.get("ts")
    if not symbol:
        raise HTTPException(400, "symbol required")
    hits = _matcher.evaluate(symbol, feats, ts=ts)
    return {"hits": hits}
