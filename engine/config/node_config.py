
import os
from decimal import Decimal
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType

def get_node_config(binance_data: BinanceDataClientConfig, binance_exec: BinanceExecClientConfig) -> TradingNodeConfig:
    # V-05 Fix: Explicit timeouts
    return TradingNodeConfig(
        timeout_connection=30.0,
        timeout_reconciliation=10.0,
        timeout_disconnection=10.0,
        timeout_post_stop=5.0,
        data_clients={"BINANCE": binance_data},
        exec_clients={"BINANCE": binance_exec},
    )

def get_binance_config() -> tuple[BinanceDataClientConfig, BinanceExecClientConfig]:
    # V-05 Fix: Keys from os.environ
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        # For dry-run/simulation, we might allow empty keys or raise error
        # Assuming simulation might not need them if using BacktestEngine, but Live does.
        pass

    # V-03 Fix: Symbols are handled in Strategy, but Config must match venue
    # Using 'USDT' margin for futures
    
    data_config = BinanceDataClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        account_type=BinanceAccountType.USDT_FUTURES,
    )
    
    exec_config = BinanceExecClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        account_type=BinanceAccountType.USDT_FUTURES,
    )
    
    return data_config, exec_config
