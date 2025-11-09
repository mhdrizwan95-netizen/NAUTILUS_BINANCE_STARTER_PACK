"""
Risk event handlers (minimal, safe defaults).

Soft handler cancels pending entries and tightens stops — stubbed with
no-ops to avoid impacting tests. Wire real implementations incrementally.
"""

from __future__ import annotations

import logging

from engine.ops.health_guard import SoftBreachGuard

_SOFT_GUARDS: dict[int, SoftBreachGuard] = {}


def on_cross_health_soft(router, cfg):
    guard = _SOFT_GUARDS.setdefault(id(router), SoftBreachGuard(router))

    async def handler(payload: dict):
        logging.getLogger(__name__).info("[RISK] soft health breach: %s", payload)
        await guard.on_cross_health_soft(payload or {})

    return handler


def on_cross_health_critical(router, cfg):
    async def handler(payload: dict):
        logging.getLogger(__name__).warning("[RISK] CRITICAL health breach: %s", payload)
        try:
            # Best-effort hard gate via trading flag
            from engine.risk_guardian import _write_trading_flag

            _write_trading_flag(False)
        except (ImportError, OSError, RuntimeError):
            pass

    return handler
