"""
Liquidation Watcher Service (The Predator Eye).

Monitors the stream of liquidation events to detect "cascades" or "waterfalls".
Calculates real-time "Liquidation Velocity" ($/sec).
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from engine import metrics
from engine.core.event_bus import EventBus
from engine.events.schemas import ExternalEvent

_LOGGER = logging.getLogger("engine.services.liquidation_watcher")


class LiquidationWatcher:
    """
    detects High-Frequency Liquidation Cascades.
    
    Logic:
    1. Listen to `market.liquidation`.
    2. Maintain a sliding window (e.g. 1s) of events per symbol.
    3. Sum the notional value ($) in the window.
    4. If Sum > THRESHOLD ($1M/sec), emit `signal.liquidation_cluster`.
    """

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._windows: dict[str, deque[tuple[float, float]]] = {}  # symbol -> deque[(ts, usd)]
        
        # Config
        self.window_size_sec = float(os.getenv("LIQU_WINDOW_SEC", "1.0"))
        self.threshold_usd = float(os.getenv("LIQU_THRESHOLD_USD", "1000000.0"))
        
        self._handler_ref: Callable[[dict[str, Any]], Any] | None = None

    async def start(self) -> None:
        """Start listening for liquidations."""
        _LOGGER.warning(
            "Starting LiquidationWatcher (Window=%.1fs, Threshold=$%.0f)",
            self.window_size_sec,
            self.threshold_usd,
        )
        # Force initialization of metric so it appears in /metrics
        metrics.liquidation_velocity_usd.labels(symbol="_INIT_", venue="BINANCE").set(0.0)
        
        async def _handle(event: dict[str, Any]) -> None:
            await self._process_event(event)

        self._handler_ref = _handle
        self.bus.subscribe("market.liquidation", _handle)

    async def stop(self) -> None:
        """Stop listening."""
        if self._handler_ref:
            self.bus.unsubscribe("market.liquidation", self._handler_ref)
            self._handler_ref = None

    async def _process_event(self, event: dict[str, Any]) -> None:
        """
        Event Format:
        {
            "type": "liquidation",
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "quantity": 0.5,
            "ts": 1234567890.123,
            "side": "sell",
            ...
        }
        """
        try:
            symbol = event.get("symbol")
            price = event.get("price", 0.0)
            qty = event.get("quantity", 0.0)
            ts = event.get("ts", time.time())
            
            if not symbol or not price or not qty:
                return

            notional = price * qty
            
            # Bucketing
            if symbol not in self._windows:
                self._windows[symbol] = deque()
            
            window = self._windows[symbol]
            window.append((ts, notional))
            
            # Prune old events
            cutoff = ts - self.window_size_sec
            while window and window[0][0] < cutoff:
                window.popleft()
                
            # Calc Velocity
            velocity = sum(n for _, n in window)
            
            # Record Metric
            metrics.liquidation_velocity_usd.labels(symbol=symbol, venue="BINANCE").set(velocity)
            
            # Check Threshold
            if velocity > self.threshold_usd:
                await self._trigger_cluster_signal(symbol, velocity, event)

        except Exception as e:
            _LOGGER.error("Error processing liquidation: %s", e, exc_info=True)

    async def _trigger_cluster_signal(self, symbol: str, velocity: float, trigger_event: dict) -> None:
        """Emit a signal that a cascade is in progress."""
        # Simple debounce or throttle could be added here, but for now we emit every time
        # the window is hot. Strategies should handle idempotency or rapid-fire updates.
        
        metrics.liquidation_clusters_total.labels(symbol=symbol, venue="BINANCE").inc()
        
        signal = {
            "type": "signal.liquidation_cluster",
            "symbol": symbol,
            "venue": "BINANCE",
            "velocity_usd": velocity,
            "trigger_side": trigger_event.get("side"),
            "trigger_price": trigger_event.get("price"),
            "ts": time.time(),
        }
        
        _LOGGER.warning(
            "🌊 LIQUIDATION CASCADE DETECTED: %s Velocity=$%.0f/s Side=%s",
            symbol,
            velocity,
            signal["trigger_side"],
        )
        
        self.bus.fire("signal.liquidation_cluster", signal)
