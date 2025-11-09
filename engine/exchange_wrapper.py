# engine/exchange_wrapper.py
import logging
import time
from typing import Any

from . import risk as _risk
from .metrics import submit_to_ack_ms

_LOG = logging.getLogger("engine.exchange_wrapper")
_ORDER_ERRORS = (RuntimeError, ValueError, ConnectionError)


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOG.debug("%s suppressed: %s", context, exc, exc_info=True)


def _record_result(ok: bool) -> None:
    rails = getattr(_risk, "RAILS", None)
    record_fn = getattr(rails, "record_result", None)
    if callable(record_fn):
        try:
            record_fn(ok)
        except _ORDER_ERRORS as exc:
            _log_suppressed("exchange_wrapper.record_result", exc)


class SafeExchangeClient:
    """Wrapper around exchange client to track latency and record venue errors."""

    def __init__(self, inner_client: Any):
        self._inner = inner_client

    def place_market_order(self, **kwargs):
        """Wrap market order with latency timing and error monitoring."""
        t0 = time.time()
        ok = False
        try:
            result = self._inner.place_market_order(**kwargs)
        except _ORDER_ERRORS as exc:
            _log_suppressed("exchange_wrapper.place_market_order", exc)
            raise
        else:
            ok = True
            return result
        finally:
            t1 = time.time()
            # Record result for breaker monitoring
            _record_result(ok)
            # Record latency for performance tracking
            latency_ms = (t1 - t0) * 1000.0
            submit_to_ack_ms.observe(latency_ms)

    # Pass through all other methods
    def __getattr__(self, name):
        return getattr(self._inner, name)
