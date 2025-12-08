
import time
import os
import threading
import logging

_LOGGER = logging.getLogger("engine.watchdog")

class Watchdog:
    def __init__(self, timeout=None):
        if timeout is None:
            timeout = float(os.getenv("WATCHDOG_TIMEOUT_SEC", "30"))
        self.timeout = timeout
        self._last_tick = time.time()
        self._running = False

    def heartbeat(self):
        self._last_tick = time.time()

    def start(self):
        if self._running: return
        self._running = True
        t = threading.Thread(target=self._monitor, daemon=True, name="watchdog")
        t.start()

    def _monitor(self):
        _LOGGER.info("Watchdog started.")
        while True:
            time.sleep(5)
            gap = time.time() - self._last_tick
            if gap > self.timeout:
                # DISABLED SUICIDE: Just warn, don't crash the engine
                # This allows the UI to still work even during Binance API issues
                _LOGGER.warning(f"WATCHDOG: Engine stalled for {gap:.1f}s. (suicide disabled)")

_INSTANCE = Watchdog()
def get_watchdog(): return _INSTANCE
