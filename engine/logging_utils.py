from __future__ import annotations

import contextvars
import logging
import os
try:
    from shared.logging import setup_logging as _setup_logging_shared
    from shared.logging import bind_request_id, reset_request_context
except ImportError:
    # Fallback placeholders
    def _setup_logging_shared(name, level):
        logging.basicConfig(level=level)
        logging.getLogger(name).warning("Shared logging module not found. Using default.")
    
    def bind_request_id(rid): return None
    def reset_request_context(tok): pass

# Re-export for compatibility
__all__ = ["setup_logging", "bind_request_id", "reset_request_context"]

_SERVICE_NAME = os.getenv("OBS_SERVICE_NAME", "engine")

def setup_logging(level: int = logging.INFO) -> None:
    """
    Sets up logging for the Engine using the shared configuration.
    Wraps the shared function to provide the default service name.
    """
    _setup_logging_shared(_SERVICE_NAME, level)

