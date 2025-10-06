# M1/M4: config.py
from dataclasses import dataclass

@dataclass
class HMMPolicyConfig:
    instrument: str = "BTCUSDT.BINANCE"
    venue: str = "BINANCE"
    max_spread_bp: float = 3.0
    max_position: int = 1
    cooldown_ms: int = 1500
    max_dd_usd: float = -50.0
    latency_ms_limit: int = 300
    qty: float = 0.001
    hmm_url: str = "http://127.0.0.1:8010"
    vwap_anchor_bps: float = 4.0
    vol_window_secs: int = 60
    retrain_kld_threshold: float = 0.25
    min_conf: float = 0.60
