from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


def _split_symbols(raw: str) -> List[str]:
    return [symbol.strip() for symbol in raw.split(",") if symbol.strip()]


class Settings(BaseSettings):
    LEDGER_DB: str = Field("/shared/manifest.sqlite")
    DATA_LANDING: str = Field("/data/incoming")
    EXCHANGE: str = Field("binance")
    SYMBOLS: str = Field("BTC/USDT,ETH/USDT")
    TIMEFRAME: str = Field("1m")
    BATCH_LIMIT: int = Field(1000, ge=100, le=5000)
    START_TS: int = Field(0)
    END_TS: int = Field(0)
    SLEEP_MS: int = Field(500, ge=0, description="Extra delay between requests (ms)")
    LOG_LEVEL: str = Field("INFO")

    @property
    def symbol_list(self) -> List[str]:
        return _split_symbols(self.SYMBOLS)


settings = Settings()
