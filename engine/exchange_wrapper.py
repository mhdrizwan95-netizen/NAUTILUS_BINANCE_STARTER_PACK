# engine/exchange_wrapper.py
import time

from .metrics import submit_to_ack_ms
from .risk import RAILS


class SafeExchangeClient:
    """Wrapper around exchange client to track latency and record venue errors."""

    def __init__(self, inner_client):
        self._inner = inner_client

    def place_market_order(self, **kwargs):
        """Wrap market order with latency timing and error monitoring."""
        t0 = time.time()
        try:
            result = self._inner.place_market_order(**kwargs)
            ok = True
            return result
        except Exception:
            ok = False
            raise
        finally:
            t1 = time.time()
            # Record result for breaker monitoring
            RAILS.record_result(ok)
            # Record latency for performance tracking
            latency_ms = (t1 - t0) * 1000.0
            submit_to_ack_ms.observe(latency_ms)

    # Pass through all other methods
    def __getattr__(self, name):
        return getattr(self._inner, name)
