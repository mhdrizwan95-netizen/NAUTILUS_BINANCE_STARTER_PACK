
import logging
import random
from decimal import Decimal
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import Venue, Symbol, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.config import InstrumentConfig
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.model.enums import AccountType, OmsType

from engine.strategies.nautilus_trend import NautilusTrendStrategy, NautilusTrendConfig

# Setup Logging
logging.getLogger("nautilus_trader").setLevel(logging.WARNING)

def generate_synthetic_data(symbol: str, days: int = 5) -> list[Bar]:
    """Generate Geometric Brownian Motion bars."""
    dt = timedelta(minutes=1)
    start_time = datetime(2024, 1, 1)
    end_time = start_time + timedelta(days=days)
    
    current_time = start_time
    price = 50000.0
    drift = 0.00001 # Slight upward drift for Trend Following
    volatility = 0.002
    
    bars = []
    # Nautilus Bar Type
    bar_type = BarType.from_str(f"{symbol}-1m-MID")
    
    random.seed(42) # Deteriministic
    np.random.seed(42)

    while current_time < end_time:
        # GBM Step
        shock = np.random.normal(0, 1)
        ret = drift + volatility * shock
        price *= (1 + ret)
        
        # OHLC (Simple approximation)
        open_ = price * (1 - 0.0005 * np.random.rand())
        high = price * (1 + 0.001 * np.random.rand())
        low = price * (1 - 0.001 * np.random.rand())
        close = price
        
        # Ensure High/Low consistency
        high = max(open_, high, close)
        low = min(open_, low, close)
        
        b = Bar(
            bar_type=bar_type,
            open=Price.from_float(open_),
            high=Price.from_float(high),
            low=Price.from_float(low),
            close=Price.from_float(close),
            volume=Quantity.from_int(100),
            ts_event=int(current_time.timestamp() * 1e9),
            ts_init=int(current_time.timestamp() * 1e9),
        )
        bars.append(b)
        current_time += dt
        
    return bars

def run_simulation(fast=10, slow=50):
    print(f"--> Running Simulation with Fast={fast}, Slow={slow}...")
    
    # 1. Config
    venue = Venue("BINANCE")
    symbol_str = "BTCUSDT-PERP.BINANCE"
    symbol = Symbol.from_str(symbol_str)
    
    # 2. Engine
    config = BacktestEngineConfig(
        trader_id="BACKTESTER",
    )
    engine = BacktestEngine(config=config)
    
    # 3. Add Venue & Instrument
    # Using TestInstrumentProvider for standard futures instrument
    instrument = TestInstrumentProvider.default_future(
        venue="BINANCE", 
        symbol="BTCUSDT-PERP"
    )
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=None, 
        starting_balances=[(instrument.quote_currency, Quantity.from_int(10000))] # 10k USDT
    )
    engine.add_instrument(instrument)
    
    # 4. Add Data
    bars = generate_synthetic_data(symbol_str, days=5)
    engine.add_data(bars)
    
    # 5. Add Strategy
    strat_config = NautilusTrendConfig(
        symbol=symbol_str,
        bar_type=f"{symbol_str}-1m-MID",
        sma_fast=fast,
        sma_slow=slow,
        quantity=Decimal("0.1"), # Trade 0.1 BTC
    )
    engine.add_strategy(NautilusTrendStrategy, strat_config)
    
    # 6. Run
    engine.run()
    
    # 7. Analyze
    report = engine.get_account_report(venue)
    stats = engine.trader.generate_account_stats(venue)
    print(f"   Net PnL: {stats.net_pnl_quote:.2f}")
    
    # Simple Sharpe check likely manual if not in stats (stats has Sharpe usually)
    # stats.sharpe_ratio might be available or calculated
    
    # Return results
    return {
        "pnl": float(stats.net_pnl_quote),
        "sharpe": float(stats.sharpe_ratio) if hasattr(stats, 'sharpe_ratio') and stats.sharpe_ratio else 0.0,
        "errors": 0 # Assuming clean run if no exception
    }

if __name__ == "__main__":
    # Optimization Loop
    best_pnl = -float("inf")
    best_params = None
    
    # Try a few combos
    params = [(10, 30), (20, 50), (5, 15)]
    
    results_log = []

    for f, s in params:
        try:
            res = run_simulation(f, s)
            results_log.append(f"Fast={f}, Slow={s} -> PnL={res['pnl']}, Sharpe={res['sharpe']}")
            
            if res["pnl"] > best_pnl:
                best_pnl = res["pnl"]
                best_params = (f, s)
        except Exception as e:
            print(f"CRASH: {e}")
            results_log.append(f"Fast={f}, Slow={s} -> CRASH: {e}")

    print("\n=== SIMULATION RESULTS ===")
    for line in results_log:
        print(line)
        
    if best_pnl > 0:
        print(f"\nSUCCESS: Profitable config found {best_params} with PnL {best_pnl}")
        # Write report
        with open("SIMULATION_REPORT.md", "w") as f:
            f.write(f"# Simulation Report\n\nWinning Config: Fast={best_params[0]}, Slow={best_params[1]}\nPnL: {best_pnl}\n\n## Logs\n" + "\n".join(results_log))
    else:
        print("\nFAILURE: No profitable config found.")

