
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List

class Settings(BaseSettings):
    LEDGER_DB: str = Field("/shared/manifest.sqlite")
    DATA_LANDING: str = Field("/data/incoming")
    EXCHANGE: str = Field("binance")
    SYMBOLS: str = Field("BTC/USDT,ETH/USDT")
    TIMEFRAME: str = Field("1m")
    BATCH_LIMIT: int = Field(1000, ge=100, le=5000)
    START_TS: int = Field(0)
    LOG_LEVEL: str = Field("INFO")

settings = Settings()
