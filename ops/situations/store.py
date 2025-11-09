from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from prometheus_client import Gauge

from ..prometheus import REGISTRY
from .models import Situation

SITUATION_PRIORITY = Gauge(
    "situation_priority",
    "Configured priority for a situation",
    ["name"],
    registry=REGISTRY,
    multiprocess_mode="max",
)


class SituationStore:
    def __init__(self, path: Path | None = None) -> None:
        env_dir = os.getenv("OPS_DATA_DIR")
        data_dir = Path(env_dir).expanduser() if env_dir else Path.cwd() / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = path or (data_dir / "situations.json")
        self._items: dict[str, Situation] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        async with self._lock:
            if self._path.exists():
                try:
                    raw = json.loads(self._path.read_text())
                    for item in raw.get("situations", []):
                        s = Situation(**item)
                        self._items[s.name] = s
                        SITUATION_PRIORITY.labels(name=s.name).set(float(s.priority))
                except (json.JSONDecodeError, ValueError):
                    self._items = {}

    async def save(self) -> None:
        async with self._lock:
            tmp = self._path.with_suffix(".tmp")
            payload = {"situations": [s.model_dump() for s in self._items.values()]}
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self._path)

    def list(self) -> list[Situation]:
        return list(self._items.values())

    def active(self) -> list[Situation]:
        return [s for s in self._items.values() if s.enabled]

    async def add_or_update(self, s: Situation) -> Situation:
        async with self._lock:
            self._items[s.name] = s
            SITUATION_PRIORITY.labels(name=s.name).set(float(s.priority))
        await self.save()
        return s

    async def update_priority(self, name: str, priority: float) -> bool:
        async with self._lock:
            s = self._items.get(name)
            if not s:
                return False
            s.priority = float(priority)
            SITUATION_PRIORITY.labels(name=name).set(float(priority))
        await self.save()
        return True

    async def patch(self, name: str, patch: dict) -> Situation | None:
        async with self._lock:
            s = self._items.get(name)
            if not s:
                return None
            data = s.model_dump()
            data.update(patch)
            s2 = Situation(**data)
            self._items[name] = s2
            SITUATION_PRIORITY.labels(name=name).set(float(s2.priority))
        await self.save()
        return s2
