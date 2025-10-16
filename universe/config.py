from __future__ import annotations

from pydantic import BaseModel
from pathlib import Path
import yaml


class UCfg(BaseModel):
    quote: str = "USDT"


CFG: UCfg
cfg_path = Path("config/universe.yaml")
if cfg_path.exists():
    y = yaml.safe_load(cfg_path.read_text()) or {}
    CFG = UCfg(quote=y.get("universe_builder", {}).get("quote", "USDT"))
else:
    CFG = UCfg()

