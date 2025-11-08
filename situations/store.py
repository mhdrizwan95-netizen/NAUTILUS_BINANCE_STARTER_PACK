from __future__ import annotations

import json
from pathlib import Path

from .schema import Situation

PATH = Path("config/situations.json")


class SituationStore:
    def __init__(self):
        self.sits: dict[str, Situation] = {}

    async def load(self):
        if PATH.exists():
            data = json.loads(PATH.read_text())
            self.sits = {s["name"]: Situation(**s) for s in data}

    def active(self):
        return list(self.sits.values())

    def update_priority(self, name: str, p: float):
        if name in self.sits:
            self.sits[name].priority = float(p)
            PATH.write_text(json.dumps([s.model_dump() for s in self.active()], indent=2))
