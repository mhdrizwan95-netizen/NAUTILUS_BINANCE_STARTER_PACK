
from __future__ import annotations

import asyncio
import logging
from typing import Any
import threading

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import MessageBus
from nautilus_trader.model.data import Signal
from nautilus_trader.model.identifiers import InstrumentId, StrategyId

# Legacy Imports
from engine.core.event_bus import BUS as LEGACY_BUS

logger = logging.getLogger(__name__)

class BridgeActor(Actor):
    """
    The Diplomat (Phase 7 Refinement).
    Connects the "Legacy BUS" to the "Nautilus Actor System".
    Strictly uses call_soon_threadsafe for legacy inputs.
    """

    def __init__(self, message_bus: MessageBus):
        super().__init__()
        self._message_bus = message_bus
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread_id: int | None = None
        
    def on_start(self) -> None:
        """
        Called when the Actor is started by the node.
        """
        self._loop = asyncio.get_running_loop()
        self._thread_id = threading.get_ident()
        
        # Subscribe to Legacy BUS topics
        # The Legacy Bus (engine.core.event_bus) generally calls handlers in the thread 
        # where 'fire' or 'publish' was called.
        LEGACY_BUS.subscribe("universe.update", self._handle_legacy_universe)
        LEGACY_BUS.subscribe("strategy.deepseek_signal", self._handle_legacy_signal_raw)
        
        logger.info("BridgeActor: STARTED. Thread-Safe Gateway Active.")

    def on_stop(self) -> None:
        """
        Called when the Actor is stopped.
        """
        LEGACY_BUS.unsubscribe("universe.update", self._handle_legacy_universe)
        LEGACY_BUS.unsubscribe("strategy.deepseek_signal", self._handle_legacy_signal_raw)
        logger.info("BridgeActor: STOPPED.")

    def _handle_legacy_universe(self, payload: dict[str, Any]) -> None:
        """
        Callback from Legacy BUS.
        May be called from ANY thread.
        """
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._inject_universe_update, payload)

    def _handle_legacy_signal_raw(self, payload: dict[str, Any]) -> None:
        """
        Callback from Legacy BUS.
        May be called from ANY thread.
        """
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._inject_signal, payload)

    def _inject_universe_update(self, payload: dict[str, Any]) -> None:
        """
        Runs in the Nautilus Reactor Loop.
        """
        symbols = payload.get("symbols", [])
        source = payload.get("source", "unknown")
        logger.info(f"BridgeActor: Received Universe Update ({len(symbols)}) from {source}")
        
        # In a real system, we might re-publish this to an internal topic
        # The Supervisor will listen to this internal signal/event
        # We can simulate an internal event if message_bus supports custom topics easily,
        # or we define a custom data type.
        # For simplicity, we just leverage the fact that we are in the loop.
        # Ideally, we publish a Message object.
        pass

    def _inject_signal(self, payload: dict[str, Any]) -> None:
        """
        Runs in the Nautilus Reactor Loop.
        Translates raw dict to Nautilus Signal.
        """
        try:
            symbol_str = payload.get("symbol")
            action = payload.get("action") # BUY/SELL/HOLD
            # Nautilus Signal expects specific structure
            # Signal(instrument_id, value, ts_init, ...)
            
            # Simple normalization
            if not symbol_str or not action:
                return

            # Construct Signal
            # Note: We need a valid InstrumentId.
            # signal_value = 1 (Buy), -1 (Sell), 0 (Hold) or string
            
            # This is a simplification. 
            # Ideally we use self.publish_signal(...) if the Actor class supports it directly,
            # or `self._message_bus.publish_signal(...)`.
            
            logger.info(f"BridgeActor: Translating Signal {symbol_str} {action}")
            # self.publish_signal(...) # Requires actual scaffolding
            
        except Exception as e:
            logger.error(f"BridgeActor: Translation Failed: {e}")
