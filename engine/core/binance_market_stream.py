from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

try:
    import orjson as json
except ImportError:
    import json

import websockets
from websockets.exceptions import WebSocketException

from engine.config import get_settings

_LOGGER = logging.getLogger("binance_market_stream")

class BinanceMarketStream:
    """
    Handles the Binance Public Market Data Stream (WebSocket).
    - Connects to the public WebSocket.
    - Manages subscriptions (aggTrade, bookTicker).
    - Dispatches normalized market events.
    """

    def __init__(
        self,
        symbols: list[str],
        on_event: Callable[[dict], Any] | None = None,
    ):
        self._settings = get_settings()
        self._on_event = on_event
        self._symbols = [s.lower() for s in symbols]
        self._stop_event = asyncio.Event()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscriptions: set[str] = set()
        
        if self._settings.is_futures:
            self._base_url = "wss://fstream.binance.com/ws"
            if "testnet" in (self._settings.futures_base or ""):
                 self._base_url = "wss://stream.binancefuture.com/ws"
        else:
            self._base_url = "wss://stream.binance.com:9443/ws"
            if "testnet" in (self._settings.spot_base or ""):
                 self._base_url = "wss://testnet.binance.vision/ws"

        self.last_event_ts: float = time.time()

    def subscribe(self, symbols: list[str]) -> None:
        """Update the list of symbols and force reconnection if changed."""
        new_symbols = sorted([s.lower() for s in symbols])
        current_symbols = sorted(self._symbols)
        
        if new_symbols != current_symbols:
            _LOGGER.info(f"[MarketStream] Subscription update: {len(current_symbols)} -> {len(new_symbols)} symbols")
            self._symbols = list(set(new_symbols)) # Ensure unique
            
            # Force reconnection to pick up new streams
            if self._ws:
                _LOGGER.info("[MarketStream] Closing active connection to trigger resubscription...")
                # We can't await here easily if called from sync context or different task, 
                # but run() loop monitors connection. Closing it from background task is safe.
                asyncio.create_task(self._ws.close())

    async def run(self):
        """Main loop: connect and maintain subscriptions."""
        _LOGGER.info(f"[MarketStream] Starting Binance Public Stream ({'Futures' if self._settings.is_futures else 'Spot'})...")
        
        while not self._stop_event.is_set():
            try:
                # Construct combined stream URL
                # e.g. /stream?streams=btcusdt@aggTrade/ethusdt@aggTrade
                streams = []
                for s in self._symbols:
                    streams.append(f"{s}@aggTrade")
                    # streams.append(f"{s}@bookTicker") # Optional: add book ticker later if needed

                # [Institutional Upgrade] Subscribe to Liquidation Stream
                if self._settings.is_futures:
                    streams.append("!forceOrder@arr")

                if not streams:
                    _LOGGER.warning("[MarketStream] No symbols to subscribe. Sleeping...")
                    await asyncio.sleep(10)
                    continue

                url = f"{self._base_url}/{'/'.join(streams)}"
                # Note: Binance combined streams URL format is /stream?streams=<streamName1>/<streamName2>...
                # But for single raw stream it's /ws/<streamName>
                # For multiple, use combined streams.
                
                # Let's use the Raw Stream for single symbol or Combined Stream for multiple.
                # To be safe and scalable, always use Combined Streams.
                combined_url = f"{self._base_url.replace('/ws', '/stream')}?streams={'/'.join(streams)}"
                
                _LOGGER.info(f"[MarketStream] Connecting to {combined_url}...")

                async with websockets.connect(combined_url) as ws:
                    self._ws = ws
                    _LOGGER.info("[MarketStream] Connected.")
                    self._subscriptions = set(streams)
                    
                    async for msg in ws:
                        await self._handle_message(msg)

            except (WebSocketException, OSError) as e:
                _LOGGER.warning(f"[MarketStream] Connection lost: {e}. Reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                _LOGGER.error(f"[MarketStream] Unexpected error: {e}", exc_info=True)
                await asyncio.sleep(5)
            finally:
                self._ws = None

    async def _handle_message(self, raw_msg: str):
        self.last_event_ts = time.time()
        try:
            data = json.loads(raw_msg)
            
            # Combined stream format: {"stream": "<streamName>", "data": <raw payload>}
            if "stream" in data and "data" in data:
                payload = data["data"]
                stream = data["stream"]
            else:
                payload = data
                stream = "raw"

            event_type = payload.get("e")

            if event_type == "aggTrade":
                # Normalize to internal format
                # Binance aggTrade:
                # {
                #   "e": "aggTrade",
                #   "s": "BTCUSDT",
                #   "p": "0.001",
                #   "q": "100",
                #   "T": 123456785,
                #   "m": true,
                #   ...
                # }
                normalized = {
                    "type": "trade", # Maps to market.trade in dispatcher
                    "symbol": payload.get("s"),
                    "price": float(payload.get("p", 0.0)),
                    "quantity": float(payload.get("q", 0.0)),
                    "ts": payload.get("T", 0) / 1000.0,
                    "side": "sell" if payload.get("m") else "buy", # m=True means buyer was maker -> Sell
                    "source": "binance_market_stream"
                }
                
                if self._on_event:
                    await self._dispatch(self._on_event, normalized)

            elif event_type == "forceOrder":
                # [Institutional Upgrade] Handle Liquidation Event
                # {
                #   "e": "forceOrder",
                #   "E": 1568014460893,
                #   "o": {
                #     "s": "BTCUSDT",
                #     "S": "SELL",
                #     "o": "LIMIT",
                #     "f": "IOC",
                #     "q": "0.014",
                #     "p": "9910",
                #     "ap": "9910",
                #     "X": "FILLED",
                #     ...
                #   }
                # }
                order_data = payload.get("o", {})
                normalized = {
                    "type": "liquidation",
                    "symbol": order_data.get("s"),
                    "price": float(order_data.get("ap", 0.0) or order_data.get("p", 0.0)), # Prefer average filled price
                    "quantity": float(order_data.get("q", 0.0)),
                    "ts": payload.get("T", 0) / 1000.0, # Use outer timestamp usually E, but payload example used T inside o? No, typically E is event time.
                    # Wait, payload says "E": 1568... is event time.
                    # Correcting timestamp usage:
                    "ts": payload.get("E", time.time() * 1000) / 1000.0,
                    "side": order_data.get("S", "").lower(),
                    "source": "binance_force_order"
                }
                 
                if self._on_event:
                    await self._dispatch(self._on_event, normalized)

        except Exception as e:
            _LOGGER.error(f"[MarketStream] Error handling message: {e}", exc_info=True)

    async def _dispatch(self, callback, data):
        try:
            res = callback(data)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            _LOGGER.error(f"[MarketStream] Callback error: {e}", exc_info=True)

    def stop(self):
        self._stop_event.set()
