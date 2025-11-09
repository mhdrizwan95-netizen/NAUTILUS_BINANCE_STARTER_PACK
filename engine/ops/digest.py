from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger("engine.digest").debug("%s suppressed: %s", context, exc, exc_info=True)


_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    asyncio.TimeoutError,
    httpx.HTTPError,
)


class DigestJob:
    def __init__(self, rollups, tg, clock=time, log=None):
        self.rollups = rollups
        self.tg = tg
        self.clock = clock
        self.log = log or logging.getLogger("engine.digest")
        self.buckets = None  # optional EventBOBuckets

    def _cfg_bool(self, name: str, default: bool) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() not in {"0", "false", "no"}

    def _cfg(self, name: str, default):
        return os.getenv(name, str(default))

    def _fmt(self, k, v):
        return f"{k}: *{v}*"

    def _summary(self) -> str:
        c = self.rollups.cnt
        trades = c.get("trades", 0)
        live_plans = c.get("plans_live", 0)
        dry_plans = c.get("plans_dry", 0)
        half = c.get("half_applied", 0)
        eff = (trades / live_plans) if live_plans else 0.0
        skips = {k: v for k, v in c.items() if k.startswith("skip_")}
        skip_lines = (
            " ".join([f"{k.replace('skip_','')}: *{v}*" for k, v in sorted(skips.items())]) or "—"
        )
        lines = [
            "*Event Breakout – Daily Digest*",
            self._fmt("Plans LIVE", live_plans),
            self._fmt("Plans DRY", dry_plans),
            self._fmt("Trades", trades),
            self._fmt("Efficiency (trades/live)", f"{eff:.2f}"),
            self._fmt("Half-size applied", half),
            f"Skips ▸ {skip_lines}",
        ]
        if self._cfg_bool("DIGEST_INCLUDE_SYMBOLS", True):
            tops = self.rollups.top_symbols("trades", k=5)
            if tops:
                symtxt = ", ".join([f"{s} *{n}*" for s, n in tops])
                lines.append(f"Top traded: {symtxt}")
        # 6h bucket section (optional)
        if (
            self._cfg_bool("DIGEST_6H_ENABLED", False)
            and getattr(self, "buckets", None) is not None
        ):
            try:
                lines.append("\n*Last 24h (6h buckets)*")
                snap = self.buckets.snapshot()
                for i, b in enumerate(snap, 1):
                    cnt = b.get("cnt", {})
                    trades_b = int(cnt.get("trades", 0))
                    live_b = int(cnt.get("plans_live", 0))
                    eff_b = (trades_b / live_b) if live_b else 0.0
                    half_b = int(cnt.get("half_applied", 0))
                    skips_b = sum(int(v) for k, v in cnt.items() if str(k).startswith("skip_"))
                    label = f"B{i}"
                    lines.append(
                        f"{label}: trades *{trades_b}*, live *{live_b}*, eff *{eff_b:.2f}*, half *{half_b}*, skips *{skips_b}*"
                    )
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("digest bucket snapshot", exc)
        return "\n".join(lines)

    async def run(self) -> None:
        if not self._cfg_bool("TELEGRAM_ENABLED", False):
            return
        interval = int(float(self._cfg("DIGEST_INTERVAL_MIN", 1440))) * 60
        while True:
            try:
                self.rollups.maybe_reset()
                text = self._summary()
                await self.tg.send(text)
                self.log.info(
                    "[DIGEST] sent len=%d live=%s trades=%s",
                    len(text),
                    self.rollups.cnt.get("plans_live", 0),
                    self.rollups.cnt.get("trades", 0),
                )
            except _SUPPRESSIBLE_EXCEPTIONS:
                self.log.exception("[DIGEST] send failed")
            await asyncio.sleep(interval)
