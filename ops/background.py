"""Background tasks feeding Command Center WebSocket streams."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence

import httpx

from ops.ui_api import broadcast_account, broadcast_price
from ops.ui_services import PortfolioService

logger = logging.getLogger(__name__)
_STREAM_ERRORS = (
    httpx.HTTPError,
    asyncio.TimeoutError,
    ConnectionError,
    RuntimeError,
    ValueError,
    TypeError,
)
_SNAPSHOT_ERRORS = _STREAM_ERRORS + (OSError,)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


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
                    await broadcast_price(
                        {
                            "type": "price",
                            "symbol": symbol,
                            "price": price,
                        }
                    )
                except _STREAM_ERRORS as exc:
                    _log_suppressed(f"price_stream.{symbol}", exc)
            await asyncio.sleep(interval)


async def account_broadcaster(portfolio: PortfolioService, interval: float = 2.0) -> None:
    while True:
        try:
            snapshot = await portfolio.snapshot()
            if snapshot:
                await broadcast_account(
                    {
                        "type": "account",
                        "equity": snapshot.get("equity"),
                        "cash": snapshot.get("cash"),
                        "exposure": snapshot.get("exposure"),
                        "pnl": snapshot.get("pnl", {}),
                        "positions": snapshot.get("positions", []),
                        "ts": snapshot.get("ts"),
                    }
                )
        except _SNAPSHOT_ERRORS as exc:
            _log_suppressed("account_broadcaster.snapshot", exc)
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
