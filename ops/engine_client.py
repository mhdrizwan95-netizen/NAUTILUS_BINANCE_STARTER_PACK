from __future__ import annotations

from typing import Any

import httpx

from ops.env import primary_engine_endpoint

ENGINE_BASE = primary_engine_endpoint()


async def market_order(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{ENGINE_BASE}/orders/market", json=payload)
        r.raise_for_status()
        return r.json()


async def get_portfolio() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{ENGINE_BASE}/portfolio")
        r.raise_for_status()
        return r.json()


async def health() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{ENGINE_BASE}/health")
        r.raise_for_status()
        return r.json()
