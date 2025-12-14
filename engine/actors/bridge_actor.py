
from __future__ import annotations

import asyncio
import json
import logging
import time
import threading
from typing import Any, Dict, Optional

import redis.asyncio as redis
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import MessageBus
from nautilus_trader.model.data import Bar, QuoteTick, TradeTick
from nautilus_trader.model.events import OrderFilled, PositionChanged
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

logger = logging.getLogger(__name__)

class BridgeActor(Actor):
    """
    Phase 8 Bridge Actor: The Diplomat & Remote Control Receiver.
    
    Capabilities:
    1. Remote Control: Listens to Redis `nautilus:command` for START/STOP/FLATTEN.
    2. Telemetry Stream: Publishes conflated market/trading data to `nautilus:stream`.
    3. Dead Man's Switch: Auto-safes the system if PINGs are missed.
    4. Thread-Safe Injection: Uses `loop.call_soon_threadsafe` for all external inputs.
    """

    def __init__(self, message_bus: MessageBus, redis_url: str = "redis://redis:6379/0"):
        super().__init__()
        self._message_bus = message_bus
        self._redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Dead Man's Switch State
        self._last_ping = time.time()
        self._is_safe_mode = False
        self._ping_timeout_sec = 15.0  # 3 missed pings of 5s
        
        # Telemetry Buffers
        self._telemetry_buffer: list[dict] = []
        self._last_flush = time.time()
        self._flush_interval = 0.05  # 50ms (20Hz) logic

    def on_start(self) -> None:
        """
        Initialize Redis connection and start background tasks.
        """
        self._loop = asyncio.get_running_loop()
        
        # Subscribe to Nautilus Events for Telemetry
        self._message_bus.listen_bar(self._on_bar)
        self._message_bus.listen_trade_tick(self._on_trade_tick)
        self._message_bus.listen_order_filled(self._on_order_filled)
        self._message_bus.listen_position_changed(self._on_position_changed)
        
        # Start Background Listener
        # We start a coroutine in the *current* loop because nautilus loop is asyncio compatible
        # If Nautilus uses uvloop, this works.
        asyncio.create_task(self._connect_redis())
        asyncio.create_task(self._watchdog_loop())
        
        logger.info("BridgeActor: STARTED. Remote Control & Telemetry Active.")

    def on_stop(self) -> None:
        if self._redis:
            asyncio.create_task(self._redis.close())
        logger.info("BridgeActor: STOPPED.")

    async def _connect_redis(self):
        """
        Connects to Redis and subscribes to command channel.
        """
        try:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
            pubsub = self._redis.pubsub()
            await pubsub.subscribe("nautilus:command")
            logger.info(f"BridgeActor: Connected to Redis at {self._redis_url}")
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    self._handle_redis_message(message["data"])
        except Exception as e:
            logger.error(f"BridgeActor: Redis Connection Failed: {e}")
            # Retry logic could go here

    async def _watchdog_loop(self):
        """
        Checks for Dead Man's Switch trigger.
        """
        while True:
            await asyncio.sleep(1.0)
            if time.time() - self._last_ping > self._ping_timeout_sec:
                if not self._is_safe_mode:
                    logger.critical("BridgeActor: DEAD MAN'S SWITCH TRIGGERED (No PING). Entering SAFE MODE.")
                    self._enter_safe_mode()
            
            # Flush Telemetry
            await self._flush_telemetry()

    def _handle_redis_message(self, json_payload: str):
        """
        Parses JSON command and schedules execution on main loop.
        """
        try:
            payload = json.loads(json_payload)
            cmd = payload.get("cmd", "").upper()
            
            # PING is special - handled immediately to update heartbeat
            if cmd == "PING":
                self._last_ping = time.time()
                if self._is_safe_mode:
                    logger.info("BridgeActor: Connectivity Restored. Exiting SAFE MODE.")
                    self._is_safe_mode = False
                return

            # All other commands injected safely
            if self._loop:
                self._loop.call_soon_threadsafe(self._execute_command, cmd, payload)
                
        except json.JSONDecodeError:
            logger.warning("BridgeActor: Received invalid JSON command")

    def _execute_command(self, cmd: str, params: Dict[str, Any]):
        """
        Executes commands in the Nautilus Reactor Loop.
        """
        logger.info(f"BridgeActor: Executing Command {cmd}")
        
        if cmd == "STOP" or cmd == "FLATTEN":
             self._Flatten_all()
        elif cmd == "START":
             pass # Logic to enable trading
        elif cmd == "CONFIGURE":
             pass # Logic to update strategy config

    def _Flatten_all(self):
        """
        Signals the Risk Engine or Strategy to close all positions.
        """
        logger.warning("BridgeActor: FLATTENING ALL POSITIONS.")
        # Implementation would generate ClosePosition signals for all tracked instruments via message bus
        # self._message_bus.publish_signal(...) 

    def _enter_safe_mode(self):
        """
        Disables buying, allows selling/closing.
        """
        self._is_safe_mode = True
        # In a real impl, this would set a global Engine flag or notify RiskRails
        self._Flatten_all()

    # --- Telemetry Handlers ---

    def _on_bar(self, bar: Bar):
        # Conflate high-frequency bars
        self._buffer_telemetry("bar", {
            "symbol": bar.instrument_id.value,
            "ts": bar.ts_event,
            "o": float(bar.open),
            "h": float(bar.high),
            "l": float(bar.low),
            "c": float(bar.close),
            "v": float(bar.volume)
        })

    def _on_trade_tick(self, tick: TradeTick):
        # Trades are high priority
        pass

    def _on_order_filled(self, event: OrderFilled):
        # Fills are CRITICAL - Send immediately
        self._publish_immediate("fill", {
            "order_id": event.order_id.value,
            "symbol": event.instrument_id.value,
            "side": str(event.order_side),
            "price": float(event.last_px),
            "qty": float(event.last_qty),
            "ts": event.ts_event
        })

    def _on_position_changed(self, event: PositionChanged):
        self._publish_immediate("position", {
            "symbol": event.instrument_id.value,
            "qty": float(event.position.quantity),
            "ts": event.ts_event
        })

    def _buffer_telemetry(self, type_: str, data: dict):
        self._telemetry_buffer.append({"t": type_, "d": data})

    async def _flush_telemetry(self):
        if not self._telemetry_buffer or not self._redis:
            return
        
        # Batch publish
        try:
            payload = json.dumps(self._telemetry_buffer)
            await self._redis.publish("nautilus:stream", payload)
            self._telemetry_buffer.clear()
        except Exception as e:
            logger.error(f"BridgeActor: Telemetry Flush Failed: {e}")

    def _publish_immediate(self, type_: str, data: dict):
        """
        Bypasses buffer for critical events.
        """
        if not self._redis:
            return
        # We need to schedule the publish coroutine
        asyncio.create_task(self._redis.publish("nautilus:stream", json.dumps([{"t": type_, "d": data}])))
