"""Data Ingester configuration."""

import os


class Settings:
    """Configuration for the data ingester service."""
    
    # Exchange to fetch data from
    EXCHANGE: str = os.getenv("EXCHANGE", "binance")
    
    # Comma-separated list of symbols to ingest
    SYMBOLS: str = os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT")
    
    # OHLCV timeframe
    TIMEFRAME: str = os.getenv("TIMEFRAME", "1m")
    
    # Directory for landing files
    DATA_LANDING: str = os.getenv("DATA_LANDING", "/ml/incoming")
    
    # Ledger database for tracking downloaded files
    LEDGER_DB: str = os.getenv("LEDGER_DB", "/ml/ledger.db")
    
    # Default start timestamp (in ms) if no watermark exists
    START_TS: int = int(os.getenv("START_TS", "0"))
    
    # Batch limit for OHLCV fetches
    BATCH_LIMIT: int = int(os.getenv("BATCH_LIMIT", "1000"))
    
    # Sleep between fetches (ms)
    SLEEP_MS: int = int(os.getenv("SLEEP_MS", "500"))


settings = Settings()
