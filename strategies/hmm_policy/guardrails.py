# M12: multi-symbol guardrails + global risk budget
from enum import Enum
import time
import numpy as np

class Block(Enum):
    OK = "OK"
    SPREAD = "SPREAD"
    CONF = "CONF"
    POS = "POS"
    DD = "DD"            # per-state drawdown
    BUDGET = "BUDGET"    # global daily budget exceeded
    NOTIONAL = "NOTIONAL"
    COOLDOWN_GLOBAL = "COOLDOWN_GLOBAL"
    KILL = "KILL"

_last_global_flip_ns = 0

def compute_vwap_anchored_fair_price(context, book, trades):
    """VWAP anchoring: running VWAP as fair price baseline."""
    if not hasattr(context, 'vwap') or context.vwap == 0:
        context.vwap = book.best_bid_price + (book.best_ask_price - book.best_bid_price) / 2
    # Update VWAP from trades
    if trades:
        for trade in trades:
            px = trade['price'] if isinstance(trade, dict) else getattr(trade, 'price', 0)
            sz = trade['size'] if isinstance(trade, dict) else getattr(trade, 'size', 0)
            context.vwap = (context.vwap * context.cum_vol + px * sz) / (context.cum_vol + sz) if (context.cum_vol + sz) > 0 else px
        context.cum_vol += sum(t['size'] if isinstance(t, dict) else getattr(t, 'size', 0) for t in trades)
    return context.vwap if hasattr(context, 'vwap') else book.best_ask_price

def compute_dynamic_spread_tolerance(context, book):
    """Dynamic spread tolerance: base + volatility adjustment."""
    base_bp = getattr(context.cfg, "max_spread_bp", 3.0)
    # Adjust by realized vol from features state
    if hasattr(context.state, 'returns'):
        realized_vol = np.std(list(context.state.returns)) if context.state.returns else 0.0
        vol_adjust = min(realized_vol * 100, 2.0)  # cap at +2bp
    else:
        vol_adjust = 0.0
    return base_bp + vol_adjust

def check_gates(context, now_ns, spread_bp, qty, portfolio, metrics, *,
                symbol_cfg, state_id, conf, mid_px, day_pnl_usd,
                state_pnl_today_usd, gross_exposure_usd):
    """M12: risk gates with multi-symbol budget, per-state DD, notional, global cooldown."""
    global _last_global_flip_ns
    if conf < context.cfg.min_conf:
        return Block.CONF
    if spread_bp > symbol_cfg.max_spread_bp:
        return Block.SPREAD
    if mid_px * qty < symbol_cfg.min_notional_usd:
        return Block.NOTIONAL
    if state_pnl_today_usd < -symbol_cfg.state_dd_limit_usd:
        return Block.DD
    if day_pnl_usd <= -context.cfg.budget.day_usd:
        return Block.BUDGET
    if gross_exposure_usd > context.cfg.budget.max_gross_usd:
        return Block.POS
    # global cooldown
    if (now_ns - _last_global_flip_ns) < (context.cfg.budget.cooldown_ms_global * 1_000_000):
        return Block.COOLDOWN_GLOBAL
    _last_global_flip_ns = now_ns
    return Block.OK
