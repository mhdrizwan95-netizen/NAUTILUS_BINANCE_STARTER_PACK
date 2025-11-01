from __future__ import annotations

"""
WSRunner — resilient wrapper around a WS client order/execution stream.

Features:
 - Reconnect with simple backoff
 - Health signals via BUS (optional): OK on connect, DEGRADED on disconnect/silence
 - Calls provided on_update(upd) coroutine for each update

All behavior is gated by cfg flags passed in at construction time.
"""

import asyncio
import random
import time
from typing import Callable, Awaitable


class WSRunner:
    def __init__(
        self,
        ws_factory: Callable[[], Awaitable[object]],
        on_update: Callable[[object], Awaitable[None]],
        bus,
        log,
        cfg: dict,
        clock=time,
    ) -> None:
        self.ws_factory = ws_factory
        self.on_update = on_update
        self.bus = bus
        self.log = log
        self.cfg = cfg
        self.clock = clock
        self.last_evt_ts = 0.0

    async def run(self) -> None:
        backoffs = [
            int(x)
            for x in str(
                self.cfg.get("WS_RECONNECT_BACKOFF_MS", "500,1000,2000")
            ).split(",")
            if str(x).strip()
        ]
        while True:
            try:
                ws = await self.ws_factory()
                self.log.info("[WS] connected")
                if self.cfg.get("WS_HEALTH_ENABLED", False):
                    try:
                        self.bus.fire(
                            "health.state", {"state": 0, "reason": "ws_connected"}
                        )
                    except Exception:
                        pass
                self.last_evt_ts = float(self.clock.time())
                async for upd in ws.order_updates():
                    self.last_evt_ts = float(self.clock.time())
                    await self.on_update(upd)
            except Exception as e:
                try:
                    self.log.warning("[WS] error: %s", e)
                except Exception:
                    pass
            finally:
                if self.cfg.get("WS_HEALTH_ENABLED", False):
                    try:
                        self.bus.fire(
                            "health.state", {"state": 1, "reason": "ws_disconnected"}
                        )
                    except Exception:
                        pass
                await self._watchdog()

            # Reconnect with jittered backoff (first step only by default)
            for b in backoffs:
                await asyncio.sleep((b + random.randint(0, 200)) / 1000.0)
                break

    async def _watchdog(self) -> None:
        if not self.cfg.get("WS_HEALTH_ENABLED", False):
            return
        timeout = int(self.cfg.get("WS_DISCONNECT_ALERT_SEC", 15))
        if (self.clock.time() - self.last_evt_ts) > timeout:
            try:
                self.bus.fire("health.state", {"state": 1, "reason": "ws_silent"})
            except Exception:
                pass
