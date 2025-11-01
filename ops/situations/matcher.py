from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from .predicates import pred_ok
from .store import SituationStore


class Matcher:
    def __init__(self, store: SituationStore):
        self.store = store
        self.cooldowns: Dict[Tuple[str, str], float] = {}
        self.recent = deque(maxlen=1000)
        self.subscribers: List[Any] = []  # queues for SSE/streaming

    def evaluate(
        self, symbol: str, feats: Dict[str, Any], ts: float | None = None
    ) -> List[Dict[str, Any]]:
        ts = ts or time.time()
        hits: List[Dict[str, Any]] = []
        for s in self.store.active():
            key = (symbol, s.name)
            if ts < self.cooldowns.get(key, 0):
                continue
            if feats.get("depth_usd", 0) < float(s.min_depth_usdt):
                continue
            if all(pred_ok(p.model_dump(), feats) for p in s.predicates):
                hit = {
                    "id": uuid4().hex,
                    "ts": ts,
                    "symbol": symbol,
                    "situation": s.name,
                    "features": feats,
                    "depth_usd": feats.get("depth_usd"),
                    "priority": float(s.priority),
                }
                hits.append(hit)
                self.cooldowns[key] = ts + float(s.cooldown_sec)
                self.recent.append(hit)
                # fan out to subscribers
                for q in list(self.subscribers):
                    try:
                        q.put_nowait(hit)
                    except Exception:
                        pass
        return hits
