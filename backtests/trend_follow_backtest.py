#!/usr/bin/env python3
"""
Backtest Harness for Trend Strategy (ML Automation Compatible)
Usage: python3 backtests/trend_follow_backtest.py --symbol BTCUSDT --days 30 --output results.json
"""
import argparse
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import replace

import pandas as pd
import numpy as np

# Add project root to path
import sys
import os
sys.path.append(os.getcwd())

from engine.strategies.trend_follow import TrendStrategyModule, load_trend_config, TrendStrategyConfig, TrendTF
from engine.config.defaults import TREND_DEFAULTS

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest")

def fetch_data(symbol: str, days: int, scenario: str = "random") -> pd.DataFrame:
    """Fetch OHLCV data for backtesting (Mock implementation for now, or use CCXT/YF)"""
    # TODO: Connect to local Ingester or CCXT
    # For verification purpose, generating synthetic trend data
    logger.info(f"Generating {days} days of synthetic data for {symbol} (Scenario: {scenario})...")
    
    dates = pd.date_range(end=datetime.now(), periods=days*24*60, freq="1min")
    df = pd.DataFrame(index=dates)
    
    # Random walk with trend
    np.random.seed(42)
    returns = np.random.normal(0, 0.001, len(dates))
    
    # Inject a trend
    if scenario == "bull_run":
         # Strong sustained uptrend to force profit
         trend = np.linspace(0, 0.30, len(dates)) # 30% gain
         returns = np.random.normal(0, 0.0005, len(dates)) # Low noise
    else:
         trend = np.linspace(0, 0.05, len(dates)) # 5% drift
    
    price = 10000 * np.exp(np.cumsum(returns) + trend)
    
    df["open"] = price
    df["high"] = price * (1 + np.abs(np.random.normal(0, 0.0005, len(dates))))
    df["low"] = price * (1 - np.abs(np.random.normal(0, 0.0005, len(dates))))
    df["close"] = price + np.random.normal(0, 0.0002, len(dates))
    df["volume"] = np.abs(np.random.normal(100, 20, len(dates)))
    
    return df

class BacktestEngine:
    def __init__(self, strategy, symbol):
        self.strategy = strategy
        self.symbol = symbol
        self.position = 0.0
        self.avg_price = 0.0
        self.cash = 10000.0
        self.initial_cash = 10000.0
        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame):
        logger.info("Starting backtest loop...")
        
        for ts, row in df.iterrows():
            timestamp = ts.timestamp()
            price = row["close"]
            
            # Feed tick to strategy
            # Note: TrendStrategy expects multiple TFs, usually driven by independent clock
            # Ideally we'd resample and feed. For this harness, we MOCK the cache directly.
            
            # 1. Update Strategy Cache with simulated candles (rolling window)
            # We construct a synthetic candle list ending at current price
            # Format: [ts, open, high, low, close, vol, ...]
            # We just mock the last 50 candles as identical or slightly noisy versions of current price to ensure indicators are calcuable
            base = self.symbol.split(".")[0]
            
            # Simple mock: previous closes are valid, current is price
            # In a real harness we would maintain a resampled dataframe. 
            # Here we just want "Trend" to detect up/down.
            # If price is rising, sma(fast) > sma(slow).
            
            mock_klines = []
            # Lookback 50 periods
            start_idx = max(0, df.index.get_loc(ts) - 50)
            end_idx = df.index.get_loc(ts)
            
            subset = df.iloc[start_idx:end_idx+1]
            for sub_ts, sub_row in subset.iterrows():
                # Binance kline format (partial): [open_time, open, high, low, close, volume, ...]
                kline = [
                    int(sub_ts.timestamp() * 1000), 
                    sub_row["open"], sub_row["high"], sub_row["low"], sub_row["close"], sub_row["volume"]
                ]
                mock_klines.append(kline)
            
            # Ensure we have enough data
            if len(mock_klines) < 20:
                 # Pad with current
                 while len(mock_klines) < 20:
                     mock_klines.insert(0, mock_klines[0])

            # Inject into strategy cache for all needed TFs
            # TrendStrategy uses "15m", "1h", "4h" usually, or whatever is in config
            for tf in ["15m", "1h", "4h", "1d"]:
                 self.strategy._cache[base][tf] = mock_klines

            decision = self.strategy.handle_tick(self.symbol, price, timestamp)
            # Debug: Sample intermittent decisions
            if int(timestamp) % 3600 == 0:
                 logger.info(f"Price: {price:.2f} | Decision: {decision}")
            
            if decision:
                logger.info(f"*** TRIGGER: {decision} at {price}")
                self._execute(decision, price, timestamp)
                
            # Mark to market
            equity = self.cash + (self.position * price)
            self.equity_curve.append({"ts": timestamp, "equity": equity})

    def _execute(self, decision, price, ts):
        side = decision.get("side", "BUY")
        quantity = 0.1 # Fixed size for sim
        
        if side == "BUY":
            cost = quantity * price
            if self.cash >= cost:
                self.cash -= cost
                self.position += quantity
                self.trades.append({"side": "BUY", "price": price, "ts": ts})
        elif side == "SELL":
             if self.position > 0:
                 self.cash += quantity * price
                 self.position -= quantity
                 self.trades.append({"side": "SELL", "price": price, "ts": ts})

    def results(self):
        equity = self.equity_curve[-1]["equity"]
        pnl = equity - self.initial_cash
        ret = pnl / self.initial_cash * 100
        
        # Calculate Sharpe
        if not self.equity_curve:
            return {}
            
        curve = pd.DataFrame(self.equity_curve).set_index("ts")
        curve["returns"] = curve["equity"].pct_change()
        sharpe = 0.0
        if curve["returns"].std() > 0:
            sharpe = (curve["returns"].mean() / curve["returns"].std()) * np.sqrt(252*24*60) # Annualized minutely

        return {
            "symbol": self.symbol,
            "total_pnl_usd": round(pnl, 2),
            "return_pct": round(ret, 2),
            "sharpe_ratio": round(sharpe, 2),
            "trades": len(self.trades)
        }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--model-tag", default="default")
    parser.add_argument("--output", default="results.json")
    parser.add_argument("--scenario", default="random", help="Data scenario: random, bull_run")
    args = parser.parse_args()

    # Load Config (Mocking env params)
    defaults = TREND_DEFAULTS.copy()
    defaults["TREND_ENABLED"] = "true"
    defaults["TREND_DRY_RUN"] = "true"
    
    # Set env vars for config loader
    os.environ["TREND_ENABLED"] = "true"
    
    # Mock Scanner
    class MockScanner:
        def current_universe(self): return [args.symbol]
    
    cfg = load_trend_config(MockScanner())
    
    # Instantiate Strategy
    strategy = TrendStrategyModule(cfg, scanner=MockScanner())
    
    # Fetch Data
    df = fetch_data(args.symbol, args.days, args.scenario)
    
    # Run
    engine = BacktestEngine(strategy, args.symbol)
    engine.run(df)
    
    # Results
    res = engine.results()
    res["model_tag"] = args.model_tag

    # Output
    logger.info(f"Backtest Complete. PnL: ${res['total_pnl_usd']} (Sharpe: {res['sharpe_ratio']})")
    
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=2))
    logger.info(f"Results saved to {out_path}")

if __name__ == "__main__":
    main()
