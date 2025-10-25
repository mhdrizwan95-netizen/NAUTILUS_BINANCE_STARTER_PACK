from __future__ import annotations

class NotifyBridge:
    """Relay BUS 'notify.telegram' events to Telegram sender."""

    def __init__(self, tg, bus, log, enabled: bool = True) -> None:
        self.tg = tg
        self.bus = bus
        self.log = log
        self.enabled = enabled
        if enabled:
            try:
                bus.subscribe("notify.telegram", self._on_msg)
            except Exception:
                pass

    async def _on_msg(self, evt: dict) -> None:
        if not self.enabled:
            return
        try:
            text = str(evt.get("text", ""))
            if not text:
                return
            await self.tg.send(text)
        except Exception as e:
            try:
                self.log.warning("[TG-BRIDGE] send failed: %s", e)
            except Exception:
                pass

