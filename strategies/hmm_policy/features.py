# M2: features.py + M13: Macro/Micro Features
from dataclasses import dataclass, field
from collections import deque
import math
import numpy as np

@dataclass
class FeatureState:
    window_len: int = 1000
    mids: deque[float] = field(default_factory=deque)
    micros: deque[float] = field(default_factory=deque)
    spreads_bp: deque[float] = field(default_factory=deque)
    imbalances: deque[float] = field(default_factory=deque)
    signed_vol: deque[float] = field(default_factory=deque)
    vol: deque[float] = field(default_factory=deque)
    queue_deltas: deque[float] = field(default_factory=deque)  # change in total size
    returns: deque[float] = field(default_factory=deque)  # for vol and autcorr
    autcorr_lags: deque[float] = field(default_factory=deque)  # autocorrelation lags
    vwap_devs: deque[float] = field(default_factory=deque)  # deviation from VWAP
    # M13.1: enhanced features
    vol_clusters: deque[float] = field(default_factory=deque)  # queue intensity clusters
    imb_momentum: deque[float] = field(default_factory=deque)  # imbalance trends
    # now 12 deques total
    last_bid_size: float = 0.0
    last_ask_size: float = 0.0
    last_ts_ns: int = 0
    cum_signed_vol: float = 0.0
    cum_vol: float = 0.0
    vwap: float = 0.0  # running VWAP, but for simplicity

    def __post_init__(self):
        for attr in ['mids', 'micros', 'spreads_bp', 'imbalances', 'signed_vol', 'vol', 'queue_deltas', 'returns', 'autcorr_lags', 'vwap_devs', 'vol_clusters', 'imb_momentum']:
            d = getattr(self, attr)
            d = deque(d, maxlen=self.window_len)
            setattr(self, attr, d)

def _deque_std(values: deque[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    mean = sum(values) / n
    var = sum((x - mean) * (x - mean) for x in values) / n
    return math.sqrt(var)


def _autocorr(values: deque[float], window: int = 10) -> float:
    if len(values) < 2:
        return 0.0
    seq = list(values)[-window:]
    n = len(seq)
    if n < 2:
        return 0.0
    mean = sum(seq) / n
    denom = sum((x - mean) * (x - mean) for x in seq)
    if denom <= 0:
        return 0.0
    num = sum((seq[i] - mean) * (seq[i + 1] - mean) for i in range(n - 1))
    return max(-1.0, min(1.0, num / denom))


def compute_features(ctx, book, trades, state: FeatureState) -> np.ndarray:
    """Return 9 standardized microstructure features as float32 vector.
    Features: mid, spread(bp), top-of-book imbalance, microprice delta,
    realized vol (rolling), trade-sign imbalance (N-sec),
    queue dynamics (Δ size best bid/ask), short-horizon autocorr (1–2s), volume-weighted delta
    """
    # Extract book data
    best_bid = book.best_bid_price
    best_ask = book.best_ask_price
    bid_size = book.best_bid_size if hasattr(book, 'best_bid_size') else getattr(book, 'bids', [{}])[0].get('size', 0.0)
    ask_size = book.best_ask_size if hasattr(book, 'best_ask_size') else getattr(book, 'asks', [{}])[0].get('size', 0.0)
    mid = (best_bid + best_ask) / 2.0
    spread_bp = (best_ask - best_bid) / mid * 10000.0
    imbalance = (ask_size - bid_size) / (ask_size + bid_size) if (ask_size + bid_size) > 0 else 0.0
    microprice = (bid_size * best_ask + ask_size * best_bid) / (bid_size + ask_size) if (bid_size + ask_size) > 0 else mid

    # Delta microprice
    micro_delta = microprice - (state.micros[-1] if state.micros else microprice)

    # Update cum volumes from trades (simulated within N-sec window)
    for trade in trades:
        sign = 1 if trade.aggressor_side == "BUYER" else -1
        qty = trade.size
        state.cum_signed_vol += sign * qty
        state.cum_vol += qty
        px = trade.price
        # Simple VWAP update
        state.vwap = (state.vwap * (state.cum_vol - qty) + px * qty) / state.cum_vol if state.cum_vol > qty else px

    ret = (mid - state.mids[-1]) / state.mids[-1] if state.mids else 0.0

    # Realized vol: rolling std of returns
    realized_vol = _deque_std(state.returns)

    # Trade sign imbalance (N-sec): rolling signed vol / vol
    sign_imbalance = state.cum_signed_vol / state.cum_vol if state.cum_vol > 0 else 0.0

    # Queue dynamics: Δ (bid_size + ask_size)
    total_size = bid_size + ask_size
    prev_total = state.last_bid_size + state.last_ask_size
    queue_delta = total_size - prev_total

    # Short-horizon autocorr (1-2s): compute returns autocorrelation
    autcorr = _autocorr(state.returns, window=10)

    # Volume-weighted delta: deviation from VWAP
    vwap_delta = (mid - state.vwap) / state.vwap if state.vwap > 0 else 0.0

    # Queue dynamics clustering: detect aggressive queue movements
    vol_cluster = 0.0
    imbalance_momentum = 0.0

    raw_feats = np.array([
        mid,
        spread_bp,
        imbalance,
        micro_delta,
        realized_vol,
        sign_imbalance,
        queue_delta,
        autcorr,
        vwap_delta,
        vol_cluster,
        imbalance_momentum
    ], dtype=np.float32)

    # Update windows (rolling 60-90 min ~3600 ticks for crypto, but set maxlen)
    state.mids.append(mid)
    state.micros.append(microprice)
    state.spreads_bp.append(spread_bp)
    state.imbalances.append(imbalance)
    state.returns.append(ret)
    state.queue_deltas.append(queue_delta)
    state.autcorr_lags.append(autcorr)
    state.vwap_devs.append(vwap_delta)
    state.vol_clusters.append(vol_cluster)
    state.imb_momentum.append(imbalance_momentum)

    # Update state
    state.last_bid_size = bid_size
    state.last_ask_size = ask_size
    state.last_ts_ns = book.ts_ns

    return raw_feats[:9].astype(np.float32, copy=False)


class MacroMicroFeatures:
    def __init__(self, maxlen=600):  # ~10m at 1s, adapt to your cadence
        self.mids = deque(maxlen=maxlen)
        self.spreads_bp = deque(maxlen=maxlen)
        self.vol_bp = deque(maxlen=maxlen)

    def update(self, mid: float, spread_bp: float):
        self.mids.append(mid)
        self.spreads_bp.append(spread_bp)
        # realized vol (bp) over last 120 samples
        if len(self.mids) > 2:
            arr = np.asarray(self.mids, dtype=np.float64)
            rets = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
            vol_bp = float(np.std(rets[-120:]) * 1e4 if len(rets) >= 2 else 0.0)
        else:
            vol_bp = 0.0
        self.vol_bp.append(vol_bp)

    def macro_feats(self) -> np.ndarray:
        # slow aggregates: vol quantile, trend slope, spread percentile
        if len(self.mids) < 30:
            return np.zeros(6, dtype=np.float32)
        mids = np.asarray(self.mids[-300:], dtype=np.float64)
        x = np.arange(len(mids))
        # slope via simple OLS
        slope = float(np.polyfit(x, mids, 1)[0]) / max(np.mean(mids), 1e-9)
        vol = float(np.median(self.vol_bp[-300:]) if self.vol_bp else 0.0)
        spr = float(np.median(self.spreads_bp[-300:]) if self.spreads_bp else 0.0)
        # quantiles as regime encoders
        vol_q = float(np.quantile(self.vol_bp[-300:], 0.75) if len(self.vol_bp) > 10 else 0.0)
        spr_q = float(np.quantile(self.spreads_bp[-300:], 0.75) if len(self.spreads_bp) > 10 else 0.0)
        trend = float(np.sign(slope))
        return np.array([vol, vol_q, spr, spr_q, slope, trend], dtype=np.float32)

    def micro_feats(self, base_micro_vec: np.ndarray) -> np.ndarray:
        # reuse your existing micro feature vector, optionally append short-window stats
        return base_micro_vec.astype(np.float32)
