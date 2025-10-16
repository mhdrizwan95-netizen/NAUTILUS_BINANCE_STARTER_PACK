from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import asyncio

from .models import Situation
from ..prometheus import REGISTRY
from prometheus_client import Gauge


SITUATION_PRIORITY = Gauge(
    "situation_priority",
    "Configured priority for a situation",
    ["name"],
    registry=REGISTRY,
    multiprocess_mode="max",
)


class SituationStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        data_dir = Path(os.getenv("OPS_DATA_DIR", "/app/data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = path or (data_dir / "situations.json")
        self._items: Dict[str, Situation] = {}
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
                except Exception:
                    # Start fresh on parse error
                    self._items = {}

    async def save(self) -> None:
        async with self._lock:
            tmp = self._path.with_suffix(".tmp")
            payload = {"situations": [s.model_dump() for s in self._items.values()]}
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self._path)

    def list(self) -> List[Situation]:
        return list(self._items.values())

    def active(self) -> List[Situation]:
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

    async def patch(self, name: str, patch: dict) -> Optional[Situation]:
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

