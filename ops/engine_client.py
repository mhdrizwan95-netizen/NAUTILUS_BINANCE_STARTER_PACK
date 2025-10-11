from __future__ import annotations

import os
from typing import Any

import httpx

ENGINE_BASE = os.getenv("ENGINE_BASE", "http://engine:8003").rstrip("/")


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
