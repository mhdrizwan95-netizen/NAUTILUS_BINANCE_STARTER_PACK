"""Backtest Suite configuration."""

import os
from dataclasses import dataclass


@dataclass
class Settings:
    """Configuration for the backtest suite."""
    
    # Data paths
    RESEARCH_DIR: str = os.getenv("RESEARCH_DIR", "/research")
    DATA_INCOMING: str = os.getenv("DATA_INCOMING", "/research/incoming")
    RESULTS_DIR: str = os.getenv("RESULTS_DIR", "/results")
    HISTORICAL_DIR: str = os.getenv("HISTORICAL_DIR", "/historical")
    
    # Ledger database
    LEDGER_DB: str = os.getenv("LEDGER_DB", "/research/manifest.sqlite")
    
    # Service endpoints
    ML_SERVICE: str = os.getenv("ML_SERVICE", "http://ml_service:8000")
    PARAM_CONTROLLER: str = os.getenv("PARAM_CONTROLLER", "http://param_controller:8002")
    
    # Simulation parameters
    STEP_MINUTES: int = int(os.getenv("STEP_MINUTES", "1"))
    RETRAIN_EVERY_MIN: int = int(os.getenv("RETRAIN_EVERY_MIN", "360"))  # 6 hours
    
    # Cost model
    COST_BPS: float = float(os.getenv("COST_BPS", "10"))  # 10 bps = 0.1%
    SLIPPAGE_BPS_PER_VOL: float = float(os.getenv("SLIPPAGE_BPS_PER_VOL", "5"))
    
    # Training mode
    EXACTLY_ONCE: bool = os.getenv("EXACTLY_ONCE", "true").lower() in ("1", "true", "yes")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()

