from __future__ import annotations

"""
Event handlers for DEX strategy wiring.
"""

import logging
from typing import Any, Dict

from engine.strategies.dex_sniper import DexSniper


logger = logging.getLogger(__name__)


def on_dex_candidate(sniper: DexSniper):
    async def handler(payload: Dict[str, Any]) -> None:
        try:
            handled = await sniper.handle_candidate(payload or {})
            if handled:
                logger.info("[DEX] candidate promoted to trade: %s", payload.get("symbol"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DEX] handler failed: %s", exc, exc_info=True)

    return handler
