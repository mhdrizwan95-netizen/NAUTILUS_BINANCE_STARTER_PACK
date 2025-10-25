def score_long_short(f):
    long = +0.9 * f.get("r15", 0.0) + 0.6 * f.get("r60", 0.0) + 0.4 * max(0.0, f.get("vol_accel_5m_over_30m", 0.0) - 1) - 0.6 * f.get("spread_over_atr", 0.0)
    short = -0.9 * f.get("r15", 0.0) - 0.6 * f.get("r60", 0.0) + 0.4 * max(0.0, f.get("vol_accel_5m_over_30m", 0.0) - 1) - 0.6 * f.get("spread_over_atr", 0.0)
    return long, short
