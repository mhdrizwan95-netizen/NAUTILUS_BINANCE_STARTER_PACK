# backtests/data_quality.py
from __future__ import annotations
import math

def check_row(i, row, prev_ts_ns):
    issues = []
    ts = int(row["ts_ns"])
    if prev_ts_ns is not None and ts < prev_ts_ns:
        issues.append("time_backwards")
    bid = row.get("bid_px", float("nan"))
    ask = row.get("ask_px", float("nan"))
    if math.isnan(bid) or math.isnan(ask):
        issues.append("nan_px")
    if bid and ask and bid > ask:
        issues.append("crossed_book")
    if "bid_sz" in row and row["bid_sz"] is not None and row["bid_sz"] < 0:
        issues.append("neg_bid_sz")
    if "ask_sz" in row and row["ask_sz"] is not None and row["ask_sz"] < 0:
        issues.append("neg_ask_sz")
    return issues, ts

def check_spread_jump(prev_mid, prev_spread_bp, mid, spread_bp, max_jump_bp=500):
    # guards absurd jumps (e.g., symbol change, feed glitch)
    issues = []
    if prev_mid and mid and abs(mid - prev_mid)/prev_mid > 0.05:
        issues.append("mid_jump_>5pct")
    if prev_spread_bp is not None and spread_bp is not None:
        if spread_bp > 1e6 or spread_bp - prev_spread_bp > max_jump_bp:
            issues.append("spread_spike")
    return issues
