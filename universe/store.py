from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict


DB = Path("/app/data/universe.json")


class UniverseStore:
    def __init__(self) -> None:
        self.state: Dict[str, dict] = {}

    async def load(self) -> None:
        if DB.exists():
            try:
                self.state = json.loads(DB.read_text())
            except Exception:
                self.state = {}

    def save(self) -> None:
        DB.parent.mkdir(parents=True, exist_ok=True)
        DB.write_text(json.dumps(self.state, indent=2))

    def merge(self, listed: list[str], ranks: dict) -> None:
        now = int(time.time())
        for s in listed:
            ent = self.state.get(s, {"bucket": "quarantine", "first_seen": now, "stats": {}})
            ent["stats"].update(ranks.get(s, {}))
            self.state[s] = ent
        # retire missing
        for s in list(self.state.keys()):
            if s not in listed:
                self.state[s]["bucket"] = "retired"
        self.save()

    def promote_demote(self) -> None:
        for s, ent in self.state.items():
            stats = ent.get("stats", {})
            age_hours = (int(time.time()) - ent.get("first_seen", int(time.time()))) / 3600.0
            if ent.get("bucket") == "quarantine" and age_hours >= 6:
                ent["bucket"] = "candidate"
        self.save()

    def bucket_sizes(self) -> dict:
        out = {"quarantine": 0, "candidate": 0, "retired": 0}
        for ent in self.state.values():
            out[ent.get("bucket", "quarantine")] += 1
        return out

    def snapshot(self) -> Dict[str, dict]:
        return self.state
