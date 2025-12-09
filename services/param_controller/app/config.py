"""Param Controller configuration."""

import os
from dataclasses import dataclass


@dataclass
class Settings:
    """Configuration for the param controller."""
    
    # Database path for preset storage
    PC_DB: str = os.getenv("PC_DB", "/shared/param_controller.db")
    
    # L2 regularization for LinTS bandit
    L2: float = float(os.getenv("BANDIT_L2", "1.0"))
    
    # Minimum exploration probability
    EPSILON: float = float(os.getenv("BANDIT_EPSILON", "0.1"))
    
    # Thompson sampling variance scale
    ALPHA: float = float(os.getenv("BANDIT_ALPHA", "1.0"))


settings = Settings()
