from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class ModelPromotionWatcher:
    """Polls model artifacts and emits BUS events when they change."""

    def __init__(self, paths: Iterable[Path], bus, poll_interval: float = 5.0) -> None:
        self._paths = [p for p in map(Path, paths) if p]
        self._bus = bus
        self._poll = max(1.0, float(poll_interval))
        self._last_mtime = 0.0
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running or not self._paths:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                _LOGGER.warning("Model watcher stop error: %s", exc, exc_info=True)
            finally:
                self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                self._probe_paths()
            except Exception as exc:  # pragma: no cover - defensive
                _LOGGER.warning("Model watcher probe error: %s", exc, exc_info=True)
            await asyncio.sleep(self._poll)

    def _probe_paths(self) -> None:
        latest_mtime = self._last_mtime
        latest_paths = []
        for path in self._paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            if stat.st_mtime > latest_mtime:
                latest_mtime = stat.st_mtime
                latest_paths = [path]
            elif stat.st_mtime == latest_mtime:
                latest_paths.append(path)

        if latest_mtime <= self._last_mtime or not latest_paths:
            return

        self._last_mtime = latest_mtime
        payload = {
            "paths": [str(p) for p in latest_paths],
            "mtime": latest_mtime,
        }
        _LOGGER.info("Detected promoted model: %s", payload["paths"])
        try:
            self._bus.fire("model.promoted", payload)
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("Failed to fire model.promoted event: %s", exc, exc_info=True)


__all__ = ["ModelPromotionWatcher"]
