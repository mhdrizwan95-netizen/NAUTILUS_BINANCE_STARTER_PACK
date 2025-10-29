from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Callable, Iterable, List, Optional

import websockets

from engine.metrics import (
    MARK_PRICE,  # mark_price_usd with venue label
    REGISTRY,
    mark_price_by_symbol,  # multiprocess-safe single-label gauge
    mark_price_freshness_sec,
)

log = logging.getLogger("binance_ws")


def _chunks(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class BinanceWS:
    """Lightweight Binance combined-stream WebSocket client.

    - Futures: uses mark price streams:  <symbol>@markPrice@1s
    - Spot:    uses mini-ticker streams: <symbol>@miniTicker

    Updates MARK_PRICE gauge and optionally calls hooks for strategy ticks.
    Designed to be fire-and-forget; handles reconnect with backoff.
    """

    def __init__(
        self,
        symbols: List[str],
        *,
        url_base: str,
        is_futures: bool,
        role: str = "trader",
        on_price_cb: Optional[Callable[[str, float, float], object]] = None,
        price_hook: Optional[Callable[[str, str, float, float], None]] = None,
        stream_type: str = "auto",
    ) -> None:
        # Symbols must be upper for reporting; WS expects lowercase in stream names
        self.symbols = [s.upper() for s in symbols if s]
        self.url_base = url_base.rstrip("/")  # e.g., wss://fstream.binance.com/stream
        self.is_futures = is_futures
        self.role = (role or os.getenv("ROLE") or "trader").lower()
        self._on_price_cb = on_price_cb
        self._price_hook = price_hook
        self.stream_type = (stream_type or "auto").lower()
        self._tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        if not self.symbols:
            return
        # Chunk to avoid URL length limits; 100 streams per connection is conservative
        for group in _chunks(self.symbols, 100):
            t = asyncio.create_task(self._run_group(group))
            self._tasks.append(t)

    async def _run_group(self, group: List[str]) -> None:
        streams = []
        for sym in group:
            stype = self._resolve_stream_type()
            if stype == "mark":
                streams.append(f"{sym.lower()}@markPrice@1s")
            elif stype == "bookticker":
                streams.append(f"{sym.lower()}@bookTicker")
            elif stype == "aggtrade":
                streams.append(f"{sym.lower()}@aggTrade")
            else:
                streams.append(f"{sym.lower()}@miniTicker")
        url = f"{self.url_base}?streams={'/'.join(streams)}"
        backoff = 1.0
        log.warning("[WS] Binance combined stream connecting: %s (streams=%d)", url, len(streams))
        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=15,
                    ping_timeout=10,
                    open_timeout=10,
                    close_timeout=5,
                    max_queue=1000,
                ) as ws:
                    log.warning("[WS] Binance WS subscribed (%d streams)", len(streams))
                    backoff = 1.0
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        data = msg.get("data") if isinstance(msg, dict) else None
                        if not isinstance(data, dict):
                            continue
                        sym = (data.get("s") or data.get("symbol") or "").upper()
                        if not sym:
                            continue
                        price = None
                        stype = self._resolve_stream_type()
                        if stype == "mark":
                            try:
                                price = float(data.get("p") or data.get("markPrice") or 0.0)
                            except Exception:
                                price = None
                        elif stype == "bookticker":
                            try:
                                ask = float(data.get("a") or data.get("bestAskPrice") or 0.0)
                                bid = float(data.get("b") or data.get("bestBidPrice") or 0.0)
                                if ask > 0 and bid > 0:
                                    price = (ask + bid) / 2.0
                                else:
                                    price = float(data.get("c") or 0.0)
                            except Exception:
                                price = None
                        elif stype == "aggtrade":
                            try:
                                price = float(data.get("p") or 0.0)
                            except Exception:
                                price = None
                        else:
                            # Spot mini-ticker fallback: last price in 'c'
                            try:
                                price = float(data.get("c") or data.get("lastPrice") or 0.0)
                            except Exception:
                                price = None
                        if not price or price <= 0:
                            continue
                        try:
                            # Update both multi-tenant and per-symbol gauges
                            MARK_PRICE.labels(symbol=sym, venue="binance").set(float(price))
                            mark_price_by_symbol.labels(symbol=sym).set(float(price))
                            # Set freshness to 0 on arrival; periodic task will age it
                            try:
                                mark_price_freshness_sec.labels(symbol=sym, venue="binance").set(0.0)
                            except Exception:
                                pass
                        except Exception:
                            pass
                        ts = float(data.get("E") or data.get("T") or 0.0) / 1000.0 if (data.get("E") or data.get("T")) else 0.0
                        if self._price_hook:
                            try:
                                self._price_hook(f"{sym}.BINANCE", sym, float(price), ts or 0.0)
                            except Exception:
                                pass
                        cb = self._on_price_cb
                        if cb:
                            try:
                                res = cb(f"{sym}.BINANCE", float(price), ts or 0.0)
                                if asyncio.iscoroutine(res):
                                    asyncio.create_task(res)  # type: ignore[arg-type]
                            except Exception:
                                pass
            except Exception as exc:
                log.warning("[WS] Binance WS error: %s", exc)
                try:
                    ctr = REGISTRY.get("ws_disconnects_total")
                    if ctr:
                        ctr.inc()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    def _resolve_stream_type(self) -> str:
        if self.stream_type == "auto":
            return "mark" if self.is_futures else "miniticker"
        if self.stream_type in {"mark", "markprice"}:
            return "mark"
        if self.stream_type in {"book", "bookticker"}:
            return "bookticker"
        if self.stream_type in {"aggtrade", "trade", "trades"}:
            return "aggtrade"
        return "miniticker"
