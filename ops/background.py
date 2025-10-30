"""Background tasks feeding Command Center WebSocket streams."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Sequence

import httpx

from ops.ui_api import broadcast_account, broadcast_price
from ops.ui_services import PortfolioService

logger = logging.getLogger(__name__)

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"


async def price_stream(symbols: Sequence[str], interval: float = 2.0) -> None:
    if not symbols:
        logger.info("price_stream: no symbols provided; skipping task")
        return

    upper_symbols = [s.upper() for s in symbols if s]
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            for symbol in upper_symbols:
                try:
                    response = await client.get(BINANCE_PRICE_URL, params={"symbol": symbol})
                    response.raise_for_status()
                    payload = response.json()
                    price = float(payload.get("price", 0.0))
                    await broadcast_price({
                        "type": "price",
                        "symbol": symbol,
                        "price": price,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.debug("price_stream: failed to fetch %s price: %s", symbol, exc)
            await asyncio.sleep(interval)


async def account_broadcaster(portfolio: PortfolioService, interval: float = 2.0) -> None:
    while True:
        try:
            snapshot = await portfolio.snapshot()
            if snapshot:
                await broadcast_account({
                    "type": "account",
                    "equity": snapshot.get("equity"),
                    "cash": snapshot.get("cash"),
                    "exposure": snapshot.get("exposure"),
                    "pnl": snapshot.get("pnl", {}),
                    "positions": snapshot.get("positions", []),
                    "ts": snapshot.get("ts"),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("account_broadcaster: failed to publish snapshot: %s", exc)
        await asyncio.sleep(interval)


def parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def default_symbols() -> list[str]:
    env = parse_symbols(os.getenv("OPS_PRICE_SYMBOLS"))
    if env:
        return env
    return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
