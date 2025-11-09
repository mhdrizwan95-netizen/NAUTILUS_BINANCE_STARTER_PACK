from __future__ import annotations

_BRIDGE_ERRORS = (AttributeError, ConnectionError, RuntimeError, TypeError, ValueError)


def _log_suppressed(logger, context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


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
            except (AttributeError, TypeError) as exc:
                self.log.warning("[TG-BRIDGE] subscribe failed: %s", exc)

    async def _on_msg(self, evt: dict) -> None:
        if not self.enabled:
            return
        try:
            text = str(evt.get("text", ""))
            if not text:
                return
            await self.tg.send(text)
        except _BRIDGE_ERRORS as exc:
            _log_suppressed(self.log, "notify.telegram.send", exc)
