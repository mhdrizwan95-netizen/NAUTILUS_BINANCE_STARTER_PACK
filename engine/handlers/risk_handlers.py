from __future__ import annotations

"""
Risk event handlers (minimal, safe defaults).

Soft handler cancels pending entries and tightens stops — stubbed with
no-ops to avoid impacting tests. Wire real implementations incrementally.
"""

import logging


def on_cross_health_soft(router, cfg):
    async def handler(payload: dict):
        logging.getLogger(__name__).info("[RISK] soft health breach: %s", payload)
        # TODO: list_open_entries / cancel, amend_stop_reduce_only
        return None
    return handler


def on_cross_health_critical(router, cfg):
    async def handler(payload: dict):
        logging.getLogger(__name__).warning("[RISK] CRITICAL health breach: %s", payload)
        try:
            # Best-effort hard gate via trading flag
            from engine.risk_guardian import _write_trading_flag
            _write_trading_flag(False)
        except Exception:
            pass
        return None
    return handler

