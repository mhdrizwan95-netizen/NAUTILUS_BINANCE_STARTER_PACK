# M2: features.py
from dataclasses import dataclass
from collections import deque
import numpy as np

@dataclass
class FeatureState:
    mids: deque
    micro: deque
    signed_vol: deque
    vol: deque
    last_ts_ns: int = 0

def compute_features(ctx, book, trades, state: FeatureState) -> np.ndarray:
    """Return standardized microstructure features as float32 ndarray.
    ctx: session context with running mean/std
    book: L2 top-of-book snapshot/delta
    trades: recent trades (aggressor flag)
    """
    # TODO M2: implement mid, spread(bp), imbalance, microprice delta, realized vol,
    # trade sign imbalance (N-sec), queue dynamics (Δsize), short-term autocorr, VW delta.
    feats = np.zeros((12,), dtype=np.float32)
    return feats
