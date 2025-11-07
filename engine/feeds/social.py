from __future__ import annotations

"""
Lightweight social mention rate-of-change estimator (stub).

Keeps a 5-minute rolling count per token and computes ROC against the
median of the prior six 5-minute buckets.

This does not fetch real social data; external feeders may call
record_mention(symbol) to update counts. Consumers can call roc(symbol)
to get a surge indicator.
"""

import time
from collections import deque, defaultdict
from typing import Dict


_BUCKET_SEC = 300.0
_HISTORY = 6
_buckets: Dict[str, deque[tuple[float, int]]] = defaultdict(lambda: deque(maxlen=_HISTORY + 1))


def _roll(symbol: str) -> None:
    now = time.time()
    q = _buckets[symbol]
    if not q or (now - q[-1][0]) >= _BUCKET_SEC:
        q.append((now, 0))


def record_mention(symbol: str) -> None:
    s = symbol.upper()
    _roll(s)
    if _buckets[s]:
        ts, cnt = _buckets[s][-1]
        _buckets[s][-1] = (ts, cnt + 1)


def roc(symbol: str) -> float:
    s = symbol.upper()
    _roll(s)
    q = list(_buckets[s])
    if not q:
        return 0.0
    current = q[-1][1]
    prev = [cnt for _, cnt in q[:-1]]
    if not prev:
        return 0.0
    prev_sorted = sorted(prev)
    mid = len(prev_sorted) // 2
    median = (
        prev_sorted[mid]
        if len(prev_sorted) % 2 == 1
        else (prev_sorted[mid - 1] + prev_sorted[mid]) / 2.0
    ) or 1.0
    return float(current) / float(median)
