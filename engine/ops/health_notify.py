from __future__ import annotations

import time
from typing import Any


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
        except Exception:
            pass

    async def on_health_state(self, evt: dict) -> None:
        if not bool(self.cfg.get("HEALTH_TG_ENABLED", False)):
            return
        try:
            new = int(evt.get("state"))
        except Exception:
            return
        reason = str(evt.get("reason", ""))
        now = float(self.clock.time())
        if new == self.last_state:
            return
        if (now - self.last_change_ts) < int(self.cfg.get("HEALTH_DEBOUNCE_SEC", 10)):
            return
        try:
            self.metrics.health_transitions_total.labels(str(self.last_state), str(new), reason).inc()
        except Exception:
            pass
        self.last_state, self.last_change_ts = new, now
        labels = {0: "OK", 1: "DEGRADED", 2: "HALTED"}
        emoji = {0: "🟢", 1: "🟡", 2: "🔴"}
        msg = f"{emoji.get(new,'❔')} *Health state:* {labels.get(new,str(new))}\n*Reason:* `{reason}`"
        try:
            await self.tg.send(msg)
        except Exception as e:
            try:
                self.log.warning("[HEALTH] Telegram send failed: %s", e)
            except Exception:
                pass

