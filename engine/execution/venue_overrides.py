from __future__ import annotations

import os
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Dict, Tuple


def _as_bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() not in {"0", "false", "no"}


@dataclass
class _TTLFlag:
    until: float


class VenueOverrides:
    """Symbol-level execution overrides with TTL and rolling stats.

    - size_mult[symbol]: multiplicative factor for requested qty (default 1.0)
    - scalp_enabled[symbol]: if False, block SCALP intent for TTL
    - maker_allowed[symbol]: if False, avoid maker posting for TTL
    - slippage_bps window: rolling BPS samples to compute avg
    """

    def __init__(self, clock=time):
        self.clock = clock
        self.size_mult: Dict[str, Tuple[float, float]] = {}  # sym -> (mult, until)
        self.scalp_block: Dict[str, _TTLFlag] = {}
        self.maker_block: Dict[str, _TTLFlag] = {}
        self._slip_cap_bps = float(
            os.getenv("AUTO_CUTBACK_SLIP_CAP_BPS", os.getenv("FUT_TAKER_MAX_SLIP_BPS", "15"))
        )
        self._cut_mult = float(os.getenv("AUTO_CUTBACK_SIZE_MULT", "0.5"))
        self._cut_dur = float(os.getenv("AUTO_CUTBACK_DURATION_MIN", "60")) * 60.0
        self._mute_thresh = int(float(os.getenv("AUTO_MUTE_SCALP_THRESHOLD", "3")))
        self._mute_window = float(os.getenv("AUTO_MUTE_SCALP_WINDOW_MIN", "10")) * 60.0
        self._mute_dur = float(os.getenv("AUTO_MUTE_SCALP_DURATION_MIN", "60")) * 60.0
        self._spread_thresh = int(float(os.getenv("AUTO_MAKER_SPREAD_THRESHOLD", "3")))
        self._spread_window = float(os.getenv("AUTO_MAKER_SPREAD_WINDOW_MIN", "15")) * 60.0
        self._spread_dur = float(os.getenv("AUTO_MAKER_SPREAD_DURATION_MIN", "30")) * 60.0
        self._slip_window = float(os.getenv("AUTO_CUTBACK_SLIP_WINDOW_MIN", "5")) * 60.0
        # rolling deques of timestamps
        self._skip_slippage: Dict[str, deque] = defaultdict(deque)
        self._spread_events: Dict[str, deque] = defaultdict(deque)
        self._slip_samples: Dict[str, deque] = defaultdict(deque)  # (ts, bps)

    # --- getters ---
    def get_size_mult(self, sym: str) -> float:
        now = self.clock.time()
        base = sym.split(".")[0].upper()
        mult, until = self.size_mult.get(base, (1.0, 0.0))
        if until and now >= until:
            self.size_mult.pop(base, None)
            return 1.0
        return float(mult or 1.0)

    def scalp_enabled(self, sym: str) -> bool:
        now = self.clock.time()
        base = sym.split(".")[0].upper()
        flag = self.scalp_block.get(base)
        if flag and now >= flag.until:
            self.scalp_block.pop(base, None)
            return True
        return flag is None

    def maker_allowed(self, sym: str) -> bool:
        now = self.clock.time()
        base = sym.split(".")[0].upper()
        flag = self.maker_block.get(base)
        if flag and now >= flag.until:
            self.maker_block.pop(base, None)
            return True
        return flag is None

    # --- event ingestion ---
    def record_slippage_sample(self, sym: str, bps: float) -> None:
        now = self.clock.time()
        base = sym.split(".")[0].upper()
        q = self._slip_samples[base]
        q.append((now, float(bps)))
        cutoff = now - self._slip_window
        while q and q[0][0] < cutoff:
            q.popleft()
        # evaluate avg
        if q:
            avg = sum(v for _, v in q) / len(q)
            if avg > self._slip_cap_bps:
                self.size_mult[base] = (self._cut_mult, now + self._cut_dur)

    def record_skip(self, sym: str, reason: str) -> None:
        now = self.clock.time()
        base = sym.split(".")[0].upper()
        if reason == "slippage":
            q = self._skip_slippage[base]
            q.append(now)
            cutoff = now - self._mute_window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._mute_thresh:
                self.scalp_block[base] = _TTLFlag(until=now + self._mute_dur)
        if reason == "spread":
            q2 = self._spread_events[base]
            q2.append(now)
            cutoff2 = now - self._spread_window
            while q2 and q2[0] < cutoff2:
                q2.popleft()
            if len(q2) >= self._spread_thresh:
                self.maker_block[base] = _TTLFlag(until=now + self._spread_dur)
