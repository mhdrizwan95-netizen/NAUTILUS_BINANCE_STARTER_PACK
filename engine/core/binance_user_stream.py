from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

import httpx
import websockets
from websockets.exceptions import WebSocketException

from engine.config import get_settings

_LOGGER = logging.getLogger("binance_user_stream")

class BinanceUserStream:
    """
    Handles the Binance User Data Stream (WebSocket).
    - Manages listenKey (create, keep-alive).
    - Connects to the WebSocket.
    - Dispatches ACCOUNT_UPDATE and ORDER_TRADE_UPDATE events.
    """

    def __init__(
        self,
        on_account_update: Callable[[dict], Any] | None = None,
        on_order_update: Callable[[dict], Any] | None = None,
    ):
        self._settings = get_settings()
        self._on_account_update = on_account_update
        self._on_order_update = on_order_update
        self._listen_key: str | None = None
        self._stop_event = asyncio.Event()
        self._base_url = self._settings.futures_base
        self._ws_base = "wss://fstream.binance.com/ws" if "fapi" in self._base_url else "wss://stream.binance.com:9443/ws"
        # Adjust WS base for testnet if needed
        if "testnet" in self._base_url:
             self._ws_base = "wss://stream.binancefuture.com/ws"
        self.last_event_ts: float = time.time()

    async def run(self):
        """Main loop: maintain listenKey and WebSocket connection."""
        if not self._settings.api_key:
            _LOGGER.warning("[UserStream] No API Key provided. User Stream disabled.")
            return

        _LOGGER.info("[UserStream] Starting Binance User Data Stream...")
        
        # Start keep-alive task
        asyncio.create_task(self._keep_alive_loop())

        while not self._stop_event.is_set():
            try:
                if not self._listen_key:
                    self._listen_key = await self._get_listen_key()
                
                if not self._listen_key:
                    _LOGGER.error("[UserStream] Failed to get listenKey. Retrying in 5s...")
                    await asyncio.sleep(5)
                    continue

                url = f"{self._ws_base}/{self._listen_key}"
                _LOGGER.info(f"[UserStream] Connecting to {url}...")

                async with websockets.connect(url) as ws:
                    _LOGGER.debug("[UserStream] Connected.")
                    async for msg in ws:
                        await self._handle_message(msg)

            except (WebSocketException, OSError) as e:
                _LOGGER.warning(f"[UserStream] Connection lost: {e}. Reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                _LOGGER.error(f"[UserStream] Unexpected error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _handle_message(self, raw_msg: str):
        self.last_event_ts = time.time()
        try:
            data = json.loads(raw_msg)
            event_type = data.get("e")

            if event_type == "listenKeyExpired":
                _LOGGER.warning("[UserStream] listenKey expired. Refreshing...")
                self._listen_key = None # Force re-fetch
            
            elif event_type == "ACCOUNT_UPDATE":
                if self._on_account_update:
                    await self._dispatch(self._on_account_update, data)
            
            elif event_type == "ORDER_TRADE_UPDATE":
                if self._on_order_update:
                    await self._dispatch(self._on_order_update, data)

        except Exception as e:
            _LOGGER.error(f"[UserStream] Error handling message: {e}", exc_info=True)

    async def _dispatch(self, callback, data):
        try:
            res = callback(data)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            _LOGGER.error(f"[UserStream] Callback error: {e}", exc_info=True)

    async def _get_listen_key(self) -> str | None:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/fapi/v1/listenKey",
                    headers={"X-MBX-APIKEY": self._settings.api_key}
                )
                resp.raise_for_status()
                return resp.json().get("listenKey")
        except Exception as e:
            _LOGGER.error(f"[UserStream] Error getting listenKey: {e}")
            return None

    async def _keep_alive_loop(self):
        """Refresh listenKey every 30 minutes."""
        while not self._stop_event.is_set():
            await asyncio.sleep(1800) # 30 minutes
            if self._listen_key:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.put(
                            f"{self._base_url}/fapi/v1/listenKey",
                            headers={"X-MBX-APIKEY": self._settings.api_key}
                        )
                    _LOGGER.debug("[UserStream] listenKey refreshed.")
                except Exception as e:
                    _LOGGER.error(f"[UserStream] Error refreshing listenKey: {e}")
                    self._listen_key = None # Force re-create on next WS loop
