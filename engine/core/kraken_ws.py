import asyncio
import inspect
import json
import logging
import os
import ssl
import time
from typing import Any, Callable

import websockets

from engine.metrics import (
    MARK_PRICE,
    POSITION_SIZE,
    ENTRY_PRICE_USD,
    UPNL_USD,
    REGISTRY,
    position_amt_by_symbol,
    unrealized_profit_by_symbol,
)

logger = logging.getLogger("kraken_ws")


async def _safe_call(cb, *args):
    if cb is None:
        return
    try:
        if asyncio.iscoroutinefunction(cb):
            asyncio.create_task(cb(*args))
            return
        res = cb(*args)
        if inspect.isawaitable(res):
            asyncio.ensure_future(res)
    except Exception as exc:
        logger.warning("[WS] callback error: %s", exc)

class KrakenWS:
    def __init__(
        self,
        products: list[str],
        url: str = "wss://demo-futures.kraken.com/ws/v1",
        portfolio=None,
        engine=None,
        role: str | None = None,
        on_price_cb=None,
        venue: str = "KRAKEN",
        rest_client: Any | None = None,
        price_hook: Callable[[str, str, float, float], None] | None = None,
    ):
        self.url = url
        self.products = products
        # Support either a direct portfolio handle or a router/engine exposing .portfolio
        self.portfolio = portfolio
        if engine is not None and getattr(engine, "portfolio", None) is not None:
            self.portfolio = engine.portfolio
        self.role = (role or os.getenv("ROLE") or "trader").lower()
        self._on_price_cb = on_price_cb
        self.venue = (venue or "").upper() or "KRAKEN"
        self._rest_client = rest_client
        self._price_hook = price_hook

    async def run(self):
        logger.info("[WS] Kraken WS connecting to %s for products=%s", self.url, self.products)
        ssl_ctx = ssl.create_default_context()
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(
                    self.url,
                    ssl=ssl_ctx,
                    ping_interval=15,
                    ping_timeout=10,
                    open_timeout=10,
                    close_timeout=5,
                    max_queue=1000,
                ) as ws:
                    sub = {"event": "subscribe", "feed": "ticker", "product_ids": self.products}
                    await ws.send(json.dumps(sub))
                    logger.info("[WS] Kraken WS subscribed to ticker feed for %s", self.products)
                    backoff = 1.0
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except Exception as exc:
                            logger.warning("[WS] invalid message: %s", exc)
                            continue

                        if data.get("feed") != "ticker":
                            continue
                        sym = data.get("product_id") or data.get("symbol")
                        if not sym:
                            continue
                        price = data.get("markPrice") or data.get("last")
                        if not price:
                            bid = data.get("bid") or 0.0
                            ask = data.get("ask") or 0.0
                            try:
                                price = (float(bid) + float(ask)) / 2.0
                            except Exception:
                                price = 0.0
                        try:
                            price_f = float(price)
                        except Exception:
                            price_f = 0.0
                        if price_f <= 0.0:
                            continue
                        MARK_PRICE.labels(symbol=sym, venue="kraken").set(price_f)
                        self._update_upnl(sym, price_f)
                        try:
                            if self._rest_client is not None:
                                cache_fn = getattr(self._rest_client, "cache_price", None)
                                if callable(cache_fn):
                                    cache_fn(sym, price_f)
                        except Exception:
                            pass
                        await _safe_call(self._emit_price, sym, price_f, data)
            except Exception as exc:
                logger.error("[WS] Kraken WS connection error: %s", exc)
                try:
                    ctr = REGISTRY.get("ws_disconnects_total")
                    if ctr:
                        ctr.inc()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    def _update_upnl(self, sym: str, mark: float):
        """Update UPNL for symbol if position exists"""
        portfolio = getattr(self, "portfolio", None)
        if portfolio is None:
            return

        try:
            if hasattr(portfolio, "update_price"):
                try:
                    portfolio.update_price(sym, mark)
                except Exception:
                    pass

            positions = None
            if hasattr(portfolio, "state"):
                positions = getattr(portfolio.state, "positions", {})
            elif hasattr(portfolio, "positions"):
                positions = portfolio.positions

            if not isinstance(positions, dict):
                return

            base_symbol = sym.split(".")[0]
            pos = positions.get(sym) or positions.get(base_symbol)
            if pos is None:
                return
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
            if abs(qty) < 1e-12:
                return

            avg_price = float(getattr(pos, "avg_price", 0.0) or 0.0)
            upnl = float(getattr(pos, "upl", (mark - avg_price) * qty))

            labels = {"symbol": base_symbol, "venue": "kraken", "role": self.role}
            UPNL_USD.labels(**labels).set(upnl)
            POSITION_SIZE.labels(**labels).set(qty)
            ENTRY_PRICE_USD.labels(**labels).set(avg_price)
            try:
                position_amt_by_symbol.labels(symbol=base_symbol).set(qty)
                unrealized_profit_by_symbol.labels(symbol=base_symbol).set(upnl)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[WS] Error updating UPNL for {sym}: {e}")

    def set_price_callback(self, cb):
        self._on_price_cb = cb

    def _emit_price(self, sym: str, price: float, payload: dict):
        cb = self._on_price_cb
        if not cb and not self._price_hook:
            return
        ts = payload.get("time") or payload.get("timestamp") or payload.get("ts") or time.time()
        qual = sym if "." in sym else f"{sym}.{self.venue}"
        if self._price_hook:
            try:
                ts_float = float(ts) if isinstance(ts, (int, float)) else time.time()
            except Exception:
                ts_float = time.time()
            try:
                self._price_hook(qual, sym, float(price), ts_float)
            except Exception as exc:
                logger.warning("[WS] price hook error for %s: %s", sym, exc)
        if not cb:
            return
        try:
            res = cb(qual, price, ts)
            if inspect.isawaitable(res):
                asyncio.ensure_future(res)
        except Exception as exc:
            logger.warning(f"[WS] Error in price callback for {sym}: {exc}")
