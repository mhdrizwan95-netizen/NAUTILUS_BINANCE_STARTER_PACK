from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PC_DB: str = Field("/shared/param_controller.sqlite")
    EPSILON: float = 0.05  # explore rate for epsilon-greedy backup
    L2: float = 1.0  # ridge for linear TS
    MAX_PRESETS: int = 12
    LOG_LEVEL: str = "INFO"


settings = Settings()
