from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger("engine.health").debug("%s suppressed: %s", context, exc, exc_info=True)


_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    asyncio.TimeoutError,
    httpx.HTTPError,
)


class HealthNotifier:
    def __init__(self, cfg: dict, bus, tg, log, clock, metrics) -> None:
        self.cfg = cfg
        self.bus = bus
        self.tg = tg
        self.log = log
        self.clock = clock
        self.metrics = metrics
        self.last_state = 0
        self.last_change_ts = 0.0
        try:
            # Subscribe
            bus.subscribe("health.state", self.on_health_state)
        except Exception as exc:
            _log_suppressed("health notifier subscribe", exc)

    async def on_health_state(self, evt: dict[str, Any]) -> None:
        if not bool(self.cfg.get("HEALTH_TG_ENABLED", False)):
            return
        state_val = evt.get("state")
        try:
            new = int(state_val)
        except (TypeError, ValueError):
            return
        reason = str(evt.get("reason", ""))
        now = float(self.clock.time())
        if new == self.last_state:
            return
        if (now - self.last_change_ts) < int(self.cfg.get("HEALTH_DEBOUNCE_SEC", 10)):
            return
        try:
            self.metrics.health_transitions_total.labels(
                str(self.last_state), str(new), reason
            ).inc()
        except Exception as exc:
            _log_suppressed("health transition metric", exc)
        self.last_state, self.last_change_ts = new, now
        labels = {0: "OK", 1: "DEGRADED", 2: "HALTED"}
        emoji = {0: "🟢", 1: "🟡", 2: "🔴"}
        msg = f"{emoji.get(new,'❔')} *Health state:* {labels.get(new,str(new))}\n*Reason:* `{reason}`"
        try:
            await self.tg.send(msg)
        except Exception as exc:
            self.log.exception("[HEALTH] Telegram send failed")
