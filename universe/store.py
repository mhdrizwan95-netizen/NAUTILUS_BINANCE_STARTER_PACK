from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

from .config import CFG


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
            ent = self.state.get(
                s, {"bucket": "quarantine", "first_seen": now, "stats": {}}
            )
            if ent.get("bucket") == "retired":
                ent["bucket"] = "quarantine"
                ent["first_seen"] = now
            ent.setdefault("healthy_scans", 0)
            ent.setdefault("drought_scans", 0)
            ent["stats"].update(ranks.get(s, {}))
            ent["last_seen"] = now
            self.state[s] = ent
        # retire missing
        for s in list(self.state.keys()):
            if s not in listed:
                self.state[s]["bucket"] = "retired"
        self.save()

    def promote_demote(self) -> None:
        thresholds = CFG.thresholds
        now = int(time.time())
        modified = False

        min_notional = thresholds.min_notional_per_min
        turnover_target = (
            min_notional * thresholds.ignition.turnover_mult
            if thresholds.ignition.turnover_mult
            else min_notional
        )

        for ent in self.state.values():
            stats = ent.get("stats", {})
            turnover = float(stats.get("turnover", 0.0) or 0.0)
            notional_per_min = float(stats.get("notional_per_min", 0.0) or 0.0)
            trade_rate = float(stats.get("trade_rate", 0.0) or 0.0)
            age_minutes = (now - ent.get("first_seen", now)) / 60.0

            meets_turnover = notional_per_min >= min_notional
            meets_ignition = turnover >= turnover_target if turnover_target else True
            meets_trade = trade_rate >= thresholds.ignition.tradecount_mult

            bucket = ent.get("bucket", "quarantine")

            if bucket == "quarantine":
                if (
                    age_minutes >= thresholds.quarantine.min_age_minutes
                    and meets_turnover
                    and meets_ignition
                    and meets_trade
                ):
                    ent["healthy_scans"] = ent.get("healthy_scans", 0) + 1
                    modified = True
                    if ent["healthy_scans"] >= thresholds.quarantine.safe_scans:
                        ent["bucket"] = "candidate"
                        ent["promoted_at"] = now
                        ent["healthy_scans"] = 0
                        ent["drought_scans"] = 0
                        modified = True
                else:
                    if ent.get("healthy_scans"):
                        ent["healthy_scans"] = 0
                        modified = True

            elif bucket == "candidate":
                if not meets_turnover or not meets_trade:
                    ent["drought_scans"] = ent.get("drought_scans", 0) + 1
                    modified = True
                else:
                    ent["drought_scans"] = 0
                    modified = True

                demote_due_drop = notional_per_min < (
                    min_notional * thresholds.demotion.notional_drop_mult
                )
                demote_due_cb = ent.get("drought_scans", 0) >= thresholds.demotion.cb_hits
                if demote_due_drop or demote_due_cb:
                    ent["bucket"] = "quarantine"
                    ent["healthy_scans"] = 0
                    ent["drought_scans"] = 0
                    modified = True

        if modified:
            self.save()

    def bucket_sizes(self) -> dict:
        out = {"quarantine": 0, "candidate": 0, "retired": 0}
        for ent in self.state.values():
            out[ent.get("bucket", "quarantine")] += 1
        return out

    def snapshot(self) -> Dict[str, dict]:
        return self.state
