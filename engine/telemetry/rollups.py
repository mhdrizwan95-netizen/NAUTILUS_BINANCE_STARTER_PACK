from __future__ import annotations

import time
from collections import Counter
from typing import List, Tuple


class EventBORollup:
    def __init__(self, clock=time):
        self.clock = clock
        self.reset_ts = self._boundary()
        self.cnt: Counter[str] = Counter()
        self.by_symbol: Counter[tuple[str, str]] = Counter()

    def _boundary(self) -> int:
        t = time.gmtime()
        return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, 0)))

    def maybe_reset(self) -> None:
        if self.clock.time() >= self.reset_ts + 86400:
            self.cnt.clear()
            self.by_symbol.clear()
            self.reset_ts = self._boundary()

    def inc(self, key: str, symbol: str | None = None, n: int = 1) -> None:
        self.cnt[key] += n
        if symbol:
            self.by_symbol[(key, symbol)] += n

    def top_symbols(self, key: str, k: int = 5) -> List[Tuple[str, int]]:
        items = [(sym, n) for (kk, sym), n in self.by_symbol.items() if kk == key]
        return sorted(items, key=lambda x: x[1], reverse=True)[:k]


class EventBOBuckets:
    """Rolling fixed-size time buckets for intraday (e.g., 6h) rollups."""

    def __init__(self, clock=time, bucket_minutes: int = 360, max_buckets: int = 4) -> None:
        self.clock = clock
        self.bucket_sec = int(bucket_minutes) * 60
        self.max_buckets = int(max_buckets)
        self.buckets: List[tuple[int, Counter, Counter]] = []

    def _current_start(self, now: float) -> int:
        return int(now // self.bucket_sec) * self.bucket_sec

    def _get_bucket(self, now: float) -> tuple[int, Counter, Counter]:
        start = self._current_start(now)
        if self.buckets and self.buckets[-1][0] == start:
            return self.buckets[-1]
        self.buckets.append((start, Counter(), Counter()))
        if len(self.buckets) > self.max_buckets:
            self.buckets.pop(0)
        return self.buckets[-1]

    def inc(self, key: str, symbol: str | None = None, n: int = 1) -> None:
        now = float(self.clock.time())
        _, cnt, cnt_sym = self._get_bucket(now)
        cnt[key] += n
        if symbol:
            cnt_sym[(key, symbol)] = cnt_sym.get((key, symbol), 0) + n

    def snapshot(self) -> List[dict]:
        out: List[dict] = []
        for start, cnt, cnt_sym in reversed(self.buckets):
            out.append(
                {
                    "start": int(start),
                    "cnt": dict(cnt),
                    "by_symbol": {sym: v for (k, sym), v in cnt_sym.items() if k == "trades"},
                }
            )
        return out
