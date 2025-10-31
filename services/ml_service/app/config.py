
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    DATA_DIR: str = Field("/data", description="mount for data")
    MODEL_DIR: str = Field("/models")
    REGISTRY_DIR: str = Field("/models/registry")
    CURRENT_SYMLINK: str = Field("/models/current")
    LEDGER_DB: str = Field("/shared/manifest.sqlite")

    HMM_STATES: int = 4
    TRAIN_WINDOW_DAYS: int = 365
    EXACTLY_ONCE: bool = False        # if true: use only new bars > training watermark (no reuse)
    TRAIN_MIN_POINTS: int = 2000
    PROMOTION_MIN_DELTA: float = 1.0
    KEEP_N_MODELS: int = 5
    AUTO_PROMOTE: bool = True

    DELETE_AFTER_PROCESS: bool = True # delete raw files once processed by a successful training round

    RETRAIN_CRON: str = "0 */6 * * *"

    REQUIRE_AUTH: bool = False
    JWT_ALG: str = "HS256"
    JWT_SECRET: Optional[str] = None
    JWT_PUBLIC_KEY: Optional[str] = None
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
