from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    LEDGER_DB: str = Field("/research/manifest.sqlite")
    RESEARCH_DIR: str = Field("/research")
    DATA_INCOMING: str = Field("/research/incoming")
    ML_SERVICE: str = Field("http://ml_service:8000")
    PARAM_CONTROLLER: str = Field("http://param_controller:8002")
    # Simulation
    SYMBOLS: str = Field("BTC/USDT")
    TIMEFRAME: str = Field("1m")
    CHUNK_ROWS: int = Field(1000, ge=100, le=20000)  # rows per ingest "tick"
    START_TS: int = Field(0)  # ms epoch; 0 -> from file start
    END_TS: int = Field(0)  # 0 -> till file end
    TRAIN_CRON_MINUTES: int = Field(360)  # retrain cadence in minutes (e.g., 6h)
    PROMOTE: bool = Field(True)
    EXACTLY_ONCE: bool = Field(False)  # mirrors ml_service mode
    TRAIN_MIN_POINTS: int = Field(2000)
    # Risk / exec
    FEE_BP: float = Field(1.0)  # 1bp per side as default
    SLIPPAGE_BP: float = Field(2.0)
    MAX_STEPS: int = Field(100000)  # limiter for sim length
    LOG_LEVEL: str = Field("INFO")


settings = Settings()
