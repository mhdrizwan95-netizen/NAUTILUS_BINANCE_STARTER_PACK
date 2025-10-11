"""
IBKR data client for real-time market data and tick subscriptions.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Callable
from ib_insync import IB, Stock, Ticker, util

from .config import IBKRConfig


class IBKRDataClient:
    """
    Provides real-time market data from Interactive Brokers.

    Supports subscriptions and price updates for stocks, forex, futures.
    """

    def __init__(self, ib: IB, cfg: Optional[IBKRConfig] = None):
        self.ib = ib
        self.cfg = cfg
        self.subscriptions: Dict[str, Ticker] = {}
        self.price_callbacks: Dict[str, List[Callable]] = {}
        self._last_prices: Dict[str, float] = {}

    def subscribe_ticker(self, symbol: str, exchange: str = "SMART") -> Optional[Ticker]:
        """
        Subscribe to real-time ticker data for a symbol.

        Args:
            symbol: Instrument symbol
            exchange: Exchange routing

        Returns:
            Ticker object or None if failed
        """
        try:
            if symbol in self.subscriptions:
                return self.subscriptions[symbol]

            # Create contract
            contract = Stock(symbol, exchange, "USD")

            # Request market data
            ticker = self.ib.reqMktData(contract, "", False, False)

            if not ticker:
                logging.warning(f"[IBKR] Failed to subscribe to {symbol}")
                return None

            # Store subscription
            self.subscriptions[symbol] = ticker

            # Set up price updates
            ticker.updateEvent += lambda ticker: self._on_ticker_update(ticker, symbol)

            logging.info(f"[IBKR] Subscribed to {symbol} market data")
            return ticker

        except Exception as e:
            logging.error(f"[IBKR] Subscription error for {symbol}: {e}")
            return None

    def unsubscribe_ticker(self, symbol: str) -> bool:
        """
        Unsubscribe from ticker data.

        Args:
            symbol: Symbol to unsubscribe from

        Returns:
            Success status
        """
        try:
            if symbol not in self.subscriptions:
                return True

            ticker = self.subscriptions[symbol]
            self.ib.cancelMktData(ticker.contract)

            del self.subscriptions[symbol]
            if symbol in self.price_callbacks:
                del self.price_callbacks[symbol]

            logging.info(f"[IBKR] Unsubscribed from {symbol}")
            return True

        except Exception as e:
            logging.error(f"[IBKR] Unsubscribe error for {symbol}: {e}")
            return False

    def get_price(self, symbol: str, use_cache: bool = True) -> Optional[float]:
        """
        Get latest price for a symbol.

        Args:
            symbol: Instrument symbol
            use_cache: Use last known price if subscription inactive

        Returns:
            Current price or None
        """
        try:
            # Check active subscription
            if symbol in self.subscriptions:
                ticker = self.subscriptions[symbol]

                # Try different price fields in priority order
                price = (
                    ticker.last or
                    ticker.close or
                    ticker.markPrice or
                    ticker.bid or
                    ticker.ask or
                    0.0
                )

                if price > 0:
                    self._last_prices[symbol] = price
                    return price

            # Fall back to cached price
            if use_cache and symbol in self._last_prices:
                return self._last_prices[symbol]

            # Try to get snapshot if no active subscription
            if symbol not in self.subscriptions:
                ticker = self.subscribe_ticker(symbol)
                if ticker:
                    self.ib.sleep(1)  # Wait for initial data
                    return self.get_price(symbol, use_cache=True)

            return None

        except Exception as e:
            logging.error(f"[IBKR] Price fetch error for {symbol}: {e}")
            return None

    def get_market_data(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Get comprehensive market data for a symbol.

        Returns:
            Dict with bid, ask, last, volume, etc.
        """
        try:
            ticker = self.subscriptions.get(symbol)

            if not ticker:
                ticker = self.subscribe_ticker(symbol)
                if not ticker:
                    return None

            return {
                "bid": ticker.bid or 0.0,
                "bid_size": ticker.bidSize or 0,
                "ask": ticker.ask or 0.0,
                "ask_size": ticker.askSize or 0,
                "last": ticker.last or 0.0,
                "last_size": ticker.lastSize or 0,
                "close": ticker.close or 0.0,
                "mark_price": ticker.markPrice or 0.0,
                "volume": ticker.volume or 0,
                "avg_volume": ticker.avgPrice or 0.0,
                "open": ticker.open or 0.0,
                "high": ticker.high or 0.0,
                "low": ticker.low or 0.0,
                "timestamps": getattr(ticker, 'time', None)
            }

        except Exception as e:
            logging.error(f"[IBKR] Market data error for {symbol}: {e}")
            return None

    def add_price_callback(self, symbol: str, callback: Callable) -> None:
        """
        Add callback for price updates on a symbol.

        Args:
            symbol: Symbol to monitor
            callback: Function called with (symbol, price) on updates
        """
        if symbol not in self.price_callbacks:
            self.price_callbacks[symbol] = []

        if callback not in self.price_callbacks[symbol]:
            self.price_callbacks[symbol].append(callback)

        # Ensure subscription exists
        if symbol not in self.subscriptions:
            self.subscribe_ticker(symbol)

    def remove_price_callback(self, symbol: str, callback: Callable) -> None:
        """Remove price callback for a symbol."""
        if symbol in self.price_callbacks:
            if callback in self.price_callbacks[symbol]:
                self.price_callbacks[symbol].remove(callback)

            if not self.price_callbacks[symbol]:
                del self.price_callbacks[symbol]

    def _on_ticker_update(self, ticker: Ticker, symbol: str) -> None:
        """Handle ticker updates and notify callbacks."""
        try:
            # Check for price change
            new_price = ticker.last or ticker.close or 0.0

            if new_price > 0 and new_price != self._last_prices.get(symbol, 0):
                self._last_prices[symbol] = new_price

                # Notify callbacks
                if symbol in self.price_callbacks:
                    for callback in self.price_callbacks[symbol]:
                        try:
                            callback(symbol, new_price)
                        except Exception as e:
                            logging.error(f"[IBKR] Price callback error: {e}")

        except Exception as e:
            logging.error(f"[IBKR] Ticker update error for {symbol}: {e}")

    def get_subscribed_symbols(self) -> List[str]:
        """Get list of currently subscribed symbols."""
        return list(self.subscriptions.keys())

    def unsubscribe_all(self) -> None:
        """Unsubscribe from all symbols."""
        symbols = list(self.subscriptions.keys())

        for symbol in symbols:
            self.unsubscribe_ticker(symbol)

        logging.info(f"[IBKR] Unsubscribed from all {len(symbols)} symbols")

    def get_last_prices(self) -> Dict[str, float]:
        """Get last cached prices for all symbols."""
        return self._last_prices.copy()
