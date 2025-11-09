"""
Event handlers for DEX strategy wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from engine.strategies.dex_sniper import DexSniper

logger = logging.getLogger(__name__)
_HANDLER_ERRORS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


def on_dex_candidate(sniper: DexSniper) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def handler(payload: dict[str, Any] | None) -> None:
        try:
            body = payload or {}
            handled = await sniper.handle_candidate(body)
            if handled:
                logger.info("[DEX] candidate promoted to trade: %s", body.get("symbol"))
        except _HANDLER_ERRORS as exc:
            _log_suppressed("dex.handlers.candidate", exc)

    return handler
