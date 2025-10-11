"""
IBKR connection utilities for Nautilus adapter.
"""
import logging
from typing import Optional
from ib_insync import IB, util

from .config import IBKRConfig


def connect_ibkr(cfg: IBKRConfig, timeout: Optional[int] = None) -> IB:
    """
    Establish connection to Interactive Brokers TWS or Gateway.

    Args:
        cfg: IBKR configuration
        timeout: Override timeout in seconds

    Returns:
        IB: Connected IB instance

    Raises:
        ConnectionError: If connection fails
    """
    try:
        # Create IB instance
        ib = IB()

        # Set timeout
        connect_timeout = timeout or cfg.timeout

        # Connect to IBKR
        connected = ib.connect(
            host=cfg.host,
            port=cfg.port,
            clientId=cfg.client_id,
            timeout=connect_timeout,
            readonly=cfg.readonly
        )

        if not connected:
            raise ConnectionError(f"Failed to connect to IBKR at {cfg.host}:{cfg.port}")

        # Verify connection
        ib.sleep(1)
        if not ib.isConnected():
            raise ConnectionError("IBKR connection verification failed")

        logging.info("32"

        return ib

    except Exception as e:
        error_msg = f"IBKR connection failed: {str(e)}"
        logging.error(error_msg)
        raise ConnectionError(error_msg) from e


def disconnect_ibkr(ib: IB) -> None:
    """Gracefully disconnect from IBKR."""
    if ib and ib.isConnected():
        try:
            ib.disconnect()
            logging.info("[IBKR] Disconnected successfully")
        except Exception as e:
            logging.warning(f"[IBKR] Error during disconnect: {e}")


def test_ibkr_connection(cfg: IBKRConfig) -> bool:
    """
    Test IBKR connection without maintaining it.

    Returns:
        bool: True if connection successful
    """
    try:
        ib = connect_ibkr(cfg, timeout=10)
        disconnect_ibkr(ib)
        return True
    except Exception as e:
        logging.debug(f"[IBKR] Connection test failed: {e}")
        return False
