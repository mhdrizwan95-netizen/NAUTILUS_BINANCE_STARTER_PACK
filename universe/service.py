from __future__ import annotations

import logging

from fastapi import FastAPI, Response
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from .adapters import fetch_exchange_info, fetch_top24h
from .store import UniverseStore
from .config import CFG


APP = FastAPI(title="universe")
STORE = UniverseStore()
REG = CollectorRegistry()
G_SIZE = Gauge("universe_size", "Symbols per bucket", ["bucket"], registry=REG)


@APP.on_event("startup")
async def boot():
    await STORE.load()


@APP.get("/health")
def health():
    return {"ok": True}


@APP.post("/tick")
def tick():
    listed = fetch_exchange_info(quote=CFG.quote)
    if not listed:
        sizes = STORE.bucket_sizes()
        for bucket, count in sizes.items():
            G_SIZE.labels(bucket).set(count)
        logging.warning(
            "Universe tick skipped: exchange info returned no symbols; keeping prior state"
        )
        return {"ok": False, "reason": "empty_exchange_info", "sizes": sizes}
    ranks = fetch_top24h(listed)
    STORE.merge(listed, ranks)
    STORE.promote_demote()
    sizes = STORE.bucket_sizes()
    for b, n in sizes.items():
        G_SIZE.labels(b).set(n)
    return {"ok": True, "sizes": sizes}


@APP.get("/universe")
def get_universe():
    return STORE.snapshot()


@APP.get("/metrics")
def metrics():
    payload = generate_latest(REG)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
