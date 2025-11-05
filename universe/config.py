from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import BaseModel


class IgnitionCfg(BaseModel):
    turnover_mult: float = 1.0
    tradecount_mult: float = 0.0
    atrp_min: float = 0.0


class QuarantineCfg(BaseModel):
    min_age_minutes: float = 360.0
    safe_scans: int = 3


class DemotionCfg(BaseModel):
    notional_drop_mult: float = 0.33
    cb_hits: int = 2


class ThresholdsCfg(BaseModel):
    min_notional_per_min: float = 0.0
    max_spread_atr: float = 1.2
    min_depth_usdt: float = 0.0
    ignition: IgnitionCfg = IgnitionCfg()
    quarantine: QuarantineCfg = QuarantineCfg()
    demotion: DemotionCfg = DemotionCfg()


class UniverseConfig(BaseModel):
    venue: str = "BINANCE"
    quote: str = "USDT"
    scan_interval_sec: int = 60
    thresholds: ThresholdsCfg = ThresholdsCfg()


CFG: UniverseConfig
cfg_path = Path("config/universe.yaml")
if cfg_path.exists():
    y = yaml.safe_load(cfg_path.read_text()) or {}
    builder = y.get("universe_builder", {}) or {}
    thresholds_cfg = ThresholdsCfg(**(y.get("thresholds", {}) or {}))
    CFG = UniverseConfig(
        venue=builder.get("venue", "BINANCE"),
        quote=builder.get("quote", "USDT"),
        scan_interval_sec=int(builder.get("scan_interval_sec", 60) or 60),
        thresholds=thresholds_cfg,
    )
else:
    CFG = UniverseConfig()
