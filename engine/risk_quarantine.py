from __future__ import annotations

"""
Symbol quarantine registry.

Purpose: temporarily block trading on symbols that triggered repeated
stop-loss exits within a short window. This reduces chop re-entries and
protects from degraded liquidity/behavior.

Defaults are conservative and the module is inert unless explicitly used
by callers (RiskRails integrates read-only via is_quarantined()).
"""

import time, os, json
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class QuarantinePolicy:
    max_stops_in_window: int = (
        2  # e.g., two stops within the window triggers quarantine
    )
    window_sec: float = 60 * 60  # 60 minutes
    quarantine_sec: float = 4 * 60 * 60  # 4 hours


class _Registry:
    def __init__(self) -> None:
        self._stops: Dict[str, list[float]] = {}
        self._blocked_until: Dict[str, float] = {}
        self.policy = QuarantinePolicy()
        self._path = os.path.join("state", "quarantine.json")
        self._load()

    def record_stop(self, symbol: str) -> None:
        sym = symbol.split(".")[0].upper()
        now = time.time()
        arr = self._stops.setdefault(sym, [])
        arr.append(now)
        cutoff = now - self.policy.window_sec
        # prune
        self._stops[sym] = [t for t in arr if t >= cutoff]
        if len(self._stops[sym]) >= self.policy.max_stops_in_window:
            self._blocked_until[sym] = now + self.policy.quarantine_sec
        self._save()

    def is_quarantined(self, symbol: str) -> Tuple[bool, float]:
        sym = symbol.split(".")[0].upper()
        until = self._blocked_until.get(sym, 0.0)
        now = time.time()
        if now >= until:
            # expire
            if sym in self._blocked_until:
                del self._blocked_until[sym]
                self._save()
            return False, 0.0
        return True, max(0.0, until - now)

    def lift(self, symbol: str) -> None:
        sym = symbol.split(".")[0].upper()
        self._blocked_until.pop(sym, None)
        self._stops.pop(sym, None)
        self._save()

    def _load(self) -> None:
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
            self._stops = {
                k: list(map(float, v)) for k, v in data.get("stops", {}).items()
            }
            self._blocked_until = {
                k: float(v) for k, v in data.get("blocked", {}).items()
            }
        except Exception:
            self._stops = {}
            self._blocked_until = {}

    def _save(self) -> None:
        try:
            os.makedirs("state", exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump({"stops": self._stops, "blocked": self._blocked_until}, fh)
        except Exception:
            pass


REGISTRY = _Registry()


def is_quarantined(symbol: str) -> tuple[bool, float]:
    return REGISTRY.is_quarantined(symbol)


def record_stop(symbol: str) -> None:
    REGISTRY.record_stop(symbol)


def lift(symbol: str) -> None:
    REGISTRY.lift(symbol)
