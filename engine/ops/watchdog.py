"""
Watchdog - Self-Healing Mechanism for Engine Health Monitoring.

Monitors the engine's event loop heartbeat and triggers process suicide
if the engine becomes frozen (zombie state). Docker restart policy handles
automatic recovery.
"""
from __future__ import annotations

import logging
import os
import threading
import time

_LOGGER = logging.getLogger(__name__)


class EngineWatchdog:
    """Monitors engine health and triggers suicide if frozen."""

    def __init__(self, freeze_threshold_seconds: float = 30.0):
        self.freeze_threshold = freeze_threshold_seconds
        self.last_tick_time = time.time()
        self._running = False
        self._thread: threading.Thread | None = None

    def heartbeat(self) -> None:
        """Called by the engine to signal it's alive."""
        self.last_tick_time = time.time()

    def start(self) -> None:
        """Start the watchdog monitoring thread."""
        if self._running:
            _LOGGER.warning("[Watchdog] Already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="WatchdogThread")
        self._thread.start()
        _LOGGER.info(f"[Watchdog] Started (freeze threshold: {self.freeze_threshold}s)")

    def stop(self) -> None:
        """Stop the watchdog (for graceful shutdown)."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        _LOGGER.info("[Watchdog] Stopped")

    def _monitor_loop(self) -> None:
        """Background thread that monitors heartbeat."""
        while self._running:
            try:
                time.sleep(5.0)  # Check every 5 seconds
                
                if not self._running:
                    break
                
                lag = time.time() - self.last_tick_time
                
                if lag > self.freeze_threshold:
                    # Engine is frozen - trigger suicide
                    _LOGGER.critical(
                        f"[Watchdog] 🚨 ENGINE FROZEN! No heartbeat for {lag:.1f}s. "
                        f"Triggering suicide. Docker will restart."
                    )
                    
                    # Give logger time to flush
                    time.sleep(0.5)
                    
                    # Hard exit - Docker restart policy takes over
                    os._exit(1)
                
                elif lag > self.freeze_threshold * 0.5:
                    # Warning: approaching freeze threshold
                    _LOGGER.warning(f"[Watchdog] ⚠️ Slow heartbeat: {lag:.1f}s lag")
            
            except Exception as exc:
                _LOGGER.error(f"[Watchdog] Monitor error: {exc}", exc_info=True)


# Global singleton
_WATCHDOG: EngineWatchdog | None = None


def get_watchdog() -> EngineWatchdog:
    """Get or create the global watchdog instance."""
    global _WATCHDOG
    if _WATCHDOG is None:
        freeze_threshold = float(os.getenv("WATCHDOG_FREEZE_THRESHOLD_SEC", "30.0"))
        _WATCHDOG = EngineWatchdog(freeze_threshold_seconds=freeze_threshold)
    return _WATCHDOG
