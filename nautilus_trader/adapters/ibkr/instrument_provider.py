"""
IBKR instrument provider for contract details and universe management.
"""
import logging
from typing import Dict, List, Optional, Any
from ib_insync import IB, Stock, Currency, Forex, Future, Contract, ContractDetails

from .config import IBKRConfig


class IBKRInstrumentProvider:
    """
    Provides instrument/contract information for Interactive Brokers instruments.
    """

    def __init__(self, ib: IB, cfg: Optional[IBKRConfig] = None):
        self.ib = ib
        self.cfg = cfg
        self._contract_cache: Dict[str, Dict[str, Any]] = {}

    def get_stock_contract(self, symbol: str, exchange: str = "SMART") -> Optional[Contract]:
        """
        Create and validate a stock contract.

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            exchange: Exchange routing (SMART, NYSE, NASDAQ, etc.)

        Returns:
            Validated ContractDetails or None
        """
        try:
            contract = Stock(symbol, exchange, "USD")

            # Get contract details
            details = self.ib.reqContractDetails(contract)

            if not details:
                logging.warning(f"[IBKR] No contract details found for {symbol}")
                return None

            # Use first detail as primary
            primary_detail = details[0]
            primary_contract = primary_detail.contract

            # Store in cache
            cached_info = {
                "symbol": primary_contract.symbol,
                "exchange": primary_contract.exchange,
                "currency": primary_contract.currency,
                "min_tick": primary_detail.minTick,
                "lot_size": primary_detail.minSize or 1,
                "market_rule_id": primary_detail.marketRuleId,
                "price_magnifier": primary_detail.priceMagnifier,
                "valid_exchanges": primary_detail.validExchanges,
                "contract": primary_contract
            }

            self._contract_cache[symbol] = cached_info
            return primary_contract

        except Exception as e:
            logging.error(f"[IBKR] Error getting stock contract for {symbol}: {e}")
            return None

    def get_forex_contract(self, symbol: str) -> Optional[Contract]:
        """
        Create and validate a forex contract.

        Args:
            symbol: Currency pair (e.g., 'EURUSD')

        Returns:
            Validated Contract or None
        """
        try:
            if len(symbol) != 6:
                logging.error(f"[IBKR] Invalid forex symbol format: {symbol}")
                return None

            base_ccy = symbol[:3]
            quote_ccy = symbol[3:]

            contract = Forex(base_ccy, quote_ccy)

            # Test contract validity
            details = self.ib.reqContractDetails(contract)

            if not details:
                logging.warning(f"[IBKR] No forex contract details for {symbol}")
                return None

            primary_contract = details[0].contract

            cached_info = {
                "symbol": symbol,
                "base_currency": base_ccy,
                "quote_currency": quote_ccy,
                "contract": primary_contract
            }

            self._contract_cache[symbol] = cached_info
            return primary_contract

        except Exception as e:
            logging.error(f"[IBKR] Error getting forex contract for {symbol}: {e}")
            return None

    def get_future_contract(self, symbol: str, expiration: str,
                          exchange: str = "CME") -> Optional[Contract]:
        """
        Create and validate a futures contract.

        Args:
            symbol: Future symbol (e.g., 'ES' for E-mini S&P 500)
            expiration: Expiration date (YYYYMM)
            exchange: Futures exchange

        Returns:
            Validated Contract or None
        """
        try:
            contract = Future(symbol, expiration, exchange)

            details = self.ib.reqContractDetails(contract)

            if not details:
                logging.warning(f"[IBKR] No future contract details for {symbol}{expiration}")
                return None

            primary_contract = details[0].contract

            cached_info = {
                "symbol": symbol,
                "expiration": expiration,
                "exchange": exchange,
                "contract": primary_contract
            }

            self._contract_cache[f"{symbol}{expiration}"] = cached_info
            return primary_contract

        except Exception as e:
            logging.error(f"[IBKR] Error getting future contract for {symbol}{expiration}: {e}")
            return None

    def list_instruments(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch contract information for multiple symbols.

        Args:
            symbols: List of instrument symbols

        Returns:
            Dict mapping symbol to contract information
        """
        results = {}

        for symbol in symbols:
            try:
                # Try stock first
                contract = self.get_stock_contract(symbol)
                if contract:
                    results[symbol] = self._contract_cache[symbol]
                    continue

                # Try forex if stock fails
                if len(symbol) == 6:
                    contract = self.get_forex_contract(symbol)
                    if contract:
                        results[symbol] = self._contract_cache[symbol]
                        continue

                logging.warning(f"[IBKR] No valid contract found for {symbol}")

            except Exception as e:
                logging.error(f"[IBKR] Error processing {symbol}: {e}")
                continue

        return results

    def clear_cache(self) -> None:
        """Clear internal contract cache."""
        self._contract_cache.clear()
        logging.info("[IBKR] Contract cache cleared")
