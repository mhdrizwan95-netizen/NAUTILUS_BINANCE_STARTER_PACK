# M12: multi-symbol + smarter risk config
import os
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class SymbolConfig:
    instrument: str
    min_notional_usd: float = 10.0
    base_qty: float = 0.001
    vwap_anchor_bps: float = 4.0
    max_spread_bp: float = 25.0
    state_dd_limit_usd: float = 20.0  # per-state daily drawdown pause

@dataclass
class RiskBudget:
    day_usd: float = 100.0          # total day risk budget across symbols
    max_gross_usd: float = 500.0    # cap on simultaneous gross exposure
    cooldown_ms_global: int = 1500  # cross-symbol global cooldown

@dataclass
class HMMPolicyConfig:
    symbols: Dict[str, SymbolConfig] = field(default_factory=dict)
    # dynamic sizing
    qty_k: float = 1.0
    qty_min: float = 0.0005
    qty_max: float = 0.01
    # risk
    budget: RiskBudget = field(default_factory=RiskBudget)
    # model confidence gate
    min_conf: float = 0.55
    # M13: hierarchical HMM toggle (macro/micro)
    use_h2: bool = False
    # M14: cross-symbol covariance risk control
    enable_portfolio_risk: bool = False
    portfolio_target_vol: float = 0.02  # Target portfolio volatility
    correlation_max_lockstep: float = 0.85  # Correlation threshold for lockstep regime
    correlation_min_divergent: float = 0.3   # Correlation threshold for divergent regime
    # legacy fields (backward compat)
    hmm_url: str = "http://127.0.0.1:8010"
    vol_window_secs: int = 60
    retrain_kld_threshold: float = 0.25

    @classmethod
    def from_env(cls):
        cfg = cls()
        # Load symbols from env (comma-separated)
        syms = os.getenv("SYMBOLS", "BTCUSDT.BINANCE,ETHUSDT.BINANCE").split(",")
        cfg.symbols = {
            sym: SymbolConfig(instrument=sym.strip()) for sym in syms
        }
        cfg.budget.day_usd = float(os.getenv("DAY_RISK_USD", 100.0))
        cfg.qty_k = float(os.getenv("QTY_K", 1.0))
        cfg.min_conf = float(os.getenv("MIN_CONF", 0.55))
        cfg.hmm_url = os.getenv("HMM_URL", "http://127.0.0.1:8010")
        return cfg

# Default factory for common use
DEFAULT_CFG = HMMPolicyConfig(symbols={
    "BTCUSDT.BINANCE": SymbolConfig(instrument="BTCUSDT.BINANCE", min_notional_usd=10),
    "ETHUSDT.BINANCE": SymbolConfig(instrument="ETHUSDT.BINANCE", min_notional_usd=10),
})
