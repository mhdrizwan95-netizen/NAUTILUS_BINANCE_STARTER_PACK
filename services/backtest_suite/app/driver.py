"""Data driver for loading and replaying historical market data."""

import glob
from pathlib import Path
from typing import Iterator

import pandas as pd
from loguru import logger

from .config import settings


@dataclass
class Bar:
    """OHLCV bar."""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str = ""
    
    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2
    
    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3


from dataclasses import dataclass


class DataDriver:
    """Loads and replays historical market data for backtesting.
    
    Supports loading from:
    - Local CSV files
    - Ledger-managed data chunks
    """
    
    def __init__(self, symbols: list[str] | None = None):
        """Initialize the data driver.
        
        Args:
            symbols: List of symbols to load (None = all available)
        """
        self.symbols = symbols or []
        self.data: dict[str, pd.DataFrame] = {}
        self._loaded = False
    
    def load_historical(self, directory: str = None) -> int:
        """Load historical data from CSV files.
        
        Args:
            directory: Directory containing CSV files
            
        Returns:
            Number of bars loaded
        """
        directory = directory or settings.HISTORICAL_DIR
        total_bars = 0
        
        # Find all CSV files
        patterns = [
            f"{directory}/*.csv",
            f"{directory}/**/*.csv",
        ]
        
        files = []
        for pattern in patterns:
            files.extend(glob.glob(pattern, recursive=True))
        
        if not files:
            logger.warning(f"No CSV files found in {directory}")
            return 0
        
        for filepath in files:
            try:
                df = pd.read_csv(filepath)
                
                # Normalize column names
                df.columns = [c.lower().strip() for c in df.columns]
                
                # Validate required columns
                required = {"timestamp", "open", "high", "low", "close", "volume"}
                if not required.issubset(set(df.columns)):
                    logger.warning(f"Skipping {filepath}: missing columns")
                    continue
                
                # Extract symbol from filename or column
                if "symbol" in df.columns:
                    symbol = df["symbol"].iloc[0]
                else:
                    # Try to extract from filename
                    name = Path(filepath).stem
                    symbol = name.split("_")[0].split("__")[0].upper()
                
                # Filter if symbols specified
                if self.symbols and symbol not in self.symbols:
                    continue
                
                # Add to data store
                df = df.sort_values("timestamp")
                
                if symbol in self.data:
                    self.data[symbol] = pd.concat([self.data[symbol], df]).drop_duplicates(
                        subset=["timestamp"]
                    ).sort_values("timestamp")
                else:
                    self.data[symbol] = df
                
                total_bars += len(df)
                logger.info(f"Loaded {len(df)} bars for {symbol} from {filepath}")
                
            except Exception as e:
                logger.error(f"Error loading {filepath}: {e}")
        
        self._loaded = True
        return total_bars
    
    def load_from_incoming(self, directory: str = None) -> int:
        """Load data from the incoming data directory.
        
        Args:
            directory: Incoming data directory
            
        Returns:
            Number of bars loaded
        """
        directory = directory or settings.DATA_INCOMING
        return self.load_historical(directory)
    
    def get_symbols(self) -> list[str]:
        """Get list of available symbols."""
        return list(self.data.keys())
    
    def get_time_range(self) -> tuple[int, int]:
        """Get the full time range across all symbols.
        
        Returns:
            Tuple of (start_ts, end_ts) in milliseconds
        """
        if not self.data:
            return (0, 0)
        
        start = min(df["timestamp"].min() for df in self.data.values())
        end = max(df["timestamp"].max() for df in self.data.values())
        return (int(start), int(end))
    
    def get_bar_at(self, symbol: str, timestamp: int) -> Bar | None:
        """Get the bar at or before the specified timestamp.
        
        Args:
            symbol: Trading symbol
            timestamp: Target timestamp in milliseconds
            
        Returns:
            Bar object or None if not found
        """
        if symbol not in self.data:
            return None
        
        df = self.data[symbol]
        mask = df["timestamp"] <= timestamp
        
        if not mask.any():
            return None
        
        row = df[mask].iloc[-1]
        return Bar(
            timestamp=int(row["timestamp"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            symbol=symbol,
        )
    
    def get_bars_range(
        self, symbol: str, start_ts: int, end_ts: int
    ) -> list[Bar]:
        """Get all bars in a time range.
        
        Args:
            symbol: Trading symbol
            start_ts: Start timestamp (inclusive)
            end_ts: End timestamp (inclusive)
            
        Returns:
            List of Bar objects
        """
        if symbol not in self.data:
            return []
        
        df = self.data[symbol]
        mask = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
        
        bars = []
        for _, row in df[mask].iterrows():
            bars.append(Bar(
                timestamp=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                symbol=symbol,
            ))
        
        return bars
    
    def iter_bars(self, symbol: str) -> Iterator[Bar]:
        """Iterate through all bars for a symbol.
        
        Yields:
            Bar objects in chronological order
        """
        if symbol not in self.data:
            return
        
        for _, row in self.data[symbol].iterrows():
            yield Bar(
                timestamp=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                symbol=symbol,
            )
    
    def compute_returns(self, symbol: str, lookback: int = 20) -> pd.Series:
        """Compute log returns for a symbol.
        
        Args:
            symbol: Trading symbol
            lookback: Number of bars for return calculation
            
        Returns:
            Series of log returns
        """
        if symbol not in self.data:
            return pd.Series()
        
        df = self.data[symbol]
        import numpy as np
        returns = np.log(df["close"] / df["close"].shift(1))
        return returns.dropna()
    
    def compute_volatility(self, symbol: str, lookback: int = 20) -> float:
        """Compute recent volatility for a symbol.
        
        Args:
            symbol: Trading symbol
            lookback: Number of bars for volatility calculation
            
        Returns:
            Annualized volatility
        """
        returns = self.compute_returns(symbol, lookback)
        if len(returns) < 2:
            return 0.02  # Default 2%
        
        import numpy as np
        std = returns.tail(lookback).std()
        # Annualize (assuming minute bars)
        return float(std * np.sqrt(525600))  # Minutes per year
