from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # File system
    DATA_DIR: str = Field("/data", description="Mounted location for raw market data (CSV, Parquet, etc.)")
    MODEL_DIR: str = Field("/models", description="Mounted location for model symlink + registry")
    REGISTRY_DIR: str = Field("/models/registry", description="Where versioned models are saved")
    CURRENT_SYMLINK: str = Field("/models/current", description="Symlink pointing at active version dir")

    # Training
    HMM_STATES: int = 4
    TRAIN_WINDOW_DAYS: int = 365
    MIN_TRAIN_INTERVAL_MIN: int = 120
    PROMOTION_METRIC: str = "val_log_likelihood"
    PROMOTION_MIN_DELTA: float = 1.0  # require some tangible lift to swap models
    KEEP_N_MODELS: int = 5
    AUTO_PROMOTE: bool = True
    TRAIN_DATA_GLOB: str = "*.csv"

    # Scheduler (when running the scheduler container)
    RETRAIN_CRON: str = "0 */6 * * *"  # every 6 hours by default

    # Auth / RBAC
    REQUIRE_AUTH: bool = True
    JWT_ALG: str = "HS256"
    JWT_SECRET: Optional[str] = None      # For HS256
    JWT_PUBLIC_KEY: Optional[str] = None  # For RS256/ES256, etc.

    # Misc
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
