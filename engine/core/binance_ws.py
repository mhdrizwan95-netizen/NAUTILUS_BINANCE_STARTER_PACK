from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections.abc import Callable, Iterable
from typing import Any

import websockets
from websockets.exceptions import WebSocketException

from engine.metrics import (
    MARK_PRICE,  # mark_price_usd with venue label
    REGISTRY,
    mark_price_by_symbol,  # multiprocess-safe single-label gauge
    mark_price_freshness_sec,
)

log = logging.getLogger("binance_ws")


def _log_suppressed(context: str, exc: Exception) -> None:
    log.debug("%s suppressed exception: %s", context, exc, exc_info=True)


def _chunks(seq: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


_JSON_ERRORS: tuple[type[Exception], ...] = (json.JSONDecodeError, TypeError)
_FLOAT_ERRORS: tuple[type[Exception], ...] = (TypeError, ValueError)
_PROM_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError)
_CALLBACK_ERRORS: tuple[type[Exception], ...] = (RuntimeError, ValueError, TypeError)
_WS_RUNTIME_ERRORS: tuple[type[Exception], ...] = (
    asyncio.TimeoutError,
    WebSocketException,
    OSError,
)


class BinanceWS:
    """Lightweight Binance combined-stream WebSocket client.

    - Futures: uses mark price streams:  <symbol>@markPrice@1s
    - Spot:    uses mini-ticker streams: <symbol>@miniTicker

    Updates MARK_PRICE gauge and optionally calls hooks for strategy ticks.
    Designed to be fire-and-forget; handles reconnect with backoff.
    """

    def __init__(
        self,
        symbols: list[str],
        *,
        url_base: str,
        is_futures: bool,
        role: str = "trader",
        on_price_cb: Callable[[str, float, float], object] | None = None,
        price_hook: Callable[[str, str, float, float], None] | None = None,
        stream_type: str = "auto",
        event_callback: Callable[[dict[str, Any]], Any] | None = None,
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
        self._event_callback = event_callback

    async def run(self) -> None:
        if not self.symbols:
            return
        # Chunk to avoid URL length limits; 100 streams per connection is conservative
        for group in _chunks(self.symbols, 100):
            t = asyncio.create_task(self._run_group(group))
            self._tasks.append(t)

    async def _run_group(self, group: list[str]) -> None:
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
        log.warning(
            "[WS] Binance combined stream connecting: %s (streams=%d)",
            url,
            len(streams),
        )
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
                        except _JSON_ERRORS as exc:
                            _log_suppressed("binance_ws.json_decode", exc)
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
                            except _FLOAT_ERRORS as exc:
                                _log_suppressed("binance_ws.mark_price_parse", exc)
                                price = None
                        elif stype == "bookticker":
                            try:
                                ask = float(data.get("a") or data.get("bestAskPrice") or 0.0)
                                bid = float(data.get("b") or data.get("bestBidPrice") or 0.0)
                                if ask > 0 and bid > 0:
                                    price = (ask + bid) / 2.0
                                else:
                                    price = float(data.get("c") or 0.0)
                            except _FLOAT_ERRORS as exc:
                                _log_suppressed("binance_ws.book_ticker_parse", exc)
                                price = None
                        elif stype == "aggtrade":
                            try:
                                price = float(data.get("p") or 0.0)
                            except _FLOAT_ERRORS as exc:
                                _log_suppressed("binance_ws.aggtrade_parse", exc)
                                price = None
                        else:
                            # Spot mini-ticker fallback: last price in 'c'
                            try:
                                price = float(data.get("c") or data.get("lastPrice") or 0.0)
                            except _FLOAT_ERRORS as exc:
                                _log_suppressed("binance_ws.miniticker_parse", exc)
                                price = None
                        if not price or price <= 0:
                            continue
                        try:
                            MARK_PRICE.labels(symbol=sym, venue="binance").set(float(price))
                            mark_price_by_symbol.labels(symbol=sym).set(float(price))
                            try:
                                mark_price_freshness_sec.labels(symbol=sym, venue="binance").set(
                                    0.0
                                )
                            except _PROM_ERRORS as exc:
                                _log_suppressed("binance_ws.mark_freshness", exc)
                        except _PROM_ERRORS as exc:
                            _log_suppressed("binance_ws.mark_metric", exc)
                        ts = (
                            float(data.get("E") or data.get("T") or 0.0) / 1000.0
                            if (data.get("E") or data.get("T"))
                            else 0.0
                        )
                        if self._price_hook:
                            try:
                                self._price_hook(f"{sym}.BINANCE", sym, float(price), ts or 0.0)
                            except _CALLBACK_ERRORS as exc:
                                _log_suppressed("binance_ws.price_hook", exc)
                        cb = self._on_price_cb
                        if cb:
                            try:
                                res = cb(f"{sym}.BINANCE", float(price), ts or 0.0)
                                if asyncio.iscoroutine(res):
                                    asyncio.create_task(res)  # type: ignore[arg-type]
                            except _CALLBACK_ERRORS as exc:
                                _log_suppressed("binance_ws.price_callback", exc)
                        event_payload = self._build_event_payload(
                            stype=stype,
                            symbol=sym,
                            price=price,
                            ts=ts or time.time(),
                            raw=data,
                        )
                        if event_payload is not None:
                            self._emit_event(event_payload)
            except _WS_RUNTIME_ERRORS as exc:
                log.warning("[WS] Binance WS error: %s", exc)
                try:
                    ctr = REGISTRY.get("ws_disconnects_total")
                    if ctr:
                        ctr.inc()
                except _PROM_ERRORS as exc:
                    _log_suppressed("binance_ws.ws_disconnect_metric", exc)
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

    def _emit_event(self, payload: dict[str, Any]) -> None:
        callback = self._event_callback
        if not callback:
            return
        try:
            result = callback(payload)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except _CALLBACK_ERRORS:
            log.debug("[WS] event dispatch failed", exc_info=True)

    def _build_event_payload(
        self,
        *,
        stype: str,
        symbol: str,
        price: float,
        ts: float,
        raw: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(price_f) or price_f <= 0.0:
            return None
        base = symbol.upper()
        qualified = f"{base}.BINANCE"
        payload: dict[str, Any] = {
            "type": "tick",
            "symbol": qualified,
            "base": base,
            "venue": "BINANCE",
            "price": price_f,
            "ts": ts or time.time(),
            "stream": stype,
        }
        if isinstance(raw, dict):
            payload["raw"] = raw
        if stype == "aggtrade":
            payload["type"] = "trade"
            qty = raw.get("q") if isinstance(raw, dict) else None
            if qty is None and isinstance(raw, dict):
                qty = raw.get("Q") or raw.get("quantity")
            try:
                payload["quantity"] = float(qty) if qty is not None else 0.0
            except (TypeError, ValueError):
                payload["quantity"] = 0.0
            if isinstance(raw, dict):
                payload["trade_id"] = raw.get("a") or raw.get("t")
                payload["is_buyer_maker"] = bool(raw.get("m"))
        elif stype == "bookticker":
            payload["type"] = "book"
            bid_price = None
            ask_price = None
            bid_qty = None
            ask_qty = None
            if isinstance(raw, dict):
                bid_price = raw.get("b") or raw.get("bidPrice")
                ask_price = raw.get("a") or raw.get("askPrice")
                bid_qty = raw.get("B") or raw.get("bidQty")
                ask_qty = raw.get("A") or raw.get("askQty")
            try:
                payload["bid_price"] = float(bid_price) if bid_price is not None else 0.0
            except (TypeError, ValueError):
                payload["bid_price"] = 0.0
            try:
                payload["ask_price"] = float(ask_price) if ask_price is not None else 0.0
            except (TypeError, ValueError):
                payload["ask_price"] = 0.0
            try:
                payload["bid_qty"] = float(bid_qty) if bid_qty is not None else 0.0
            except (TypeError, ValueError):
                payload["bid_qty"] = 0.0
            try:
                payload["ask_qty"] = float(ask_qty) if ask_qty is not None else 0.0
            except (TypeError, ValueError):
                payload["ask_qty"] = 0.0
        else:
            if isinstance(raw, dict):
                vol = raw.get("q") or raw.get("Q") or raw.get("volume") or raw.get("v")
            else:
                vol = None
            try:
                payload["volume"] = float(vol) if vol is not None else None
            except (TypeError, ValueError):
                payload["volume"] = None
        return payload
