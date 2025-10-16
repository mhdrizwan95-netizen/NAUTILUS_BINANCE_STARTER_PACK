import numpy as np


def compute_feats(klines, book):
    closes = [float(k[4]) for k in klines[-60:]]
    vols = [float(k[5]) for k in klines[-60:]]
    last = closes[-1]
    vwap = np.average(closes, weights=vols) if sum(vols) > 0 else last
    rsi = 50.0 if len(closes) < 15 else _rsi(closes, 14)
    vwap_dev = (last - vwap) / vwap if vwap else 0.0
    r15 = (last - closes[-16]) / closes[-16] if len(closes) > 16 else 0.0
    r60 = (last - closes[0]) / closes[0] if closes else 0.0
    vol_accel_5m_over_30m = (
        (sum(vols[-5:]) / max(1e-9, np.median(vols[-30:]))) if len(vols) >= 30 else 0.0
    )
    # Also compute 1m-over-30m acceleration to match situations predicates
    vol_accel_1m_over_30m = (
        (vols[-1] / max(1e-9, np.median(vols[-30:]))) if len(vols) >= 30 else 0.0
    )
    spread = float(book["asks"][0][0]) - float(book["bids"][0][0])
    atr = _atr(klines[-20:]) or (0.001 * last)
    spread_over_atr = spread / max(1e-9, atr)
    depth_usd = sum(float(x[1]) * float(x[0]) for x in book["bids"][:5]) + sum(
        float(x[1]) * float(x[0]) for x in book["asks"][:5]
    )
    return dict(
        last=last,
        vwap_dev=vwap_dev,
        rsi_14=rsi,
        r15=r15,
        r60=r60,
        vol_accel_5m_over_30m=vol_accel_5m_over_30m,
        vol_accel_1m_over_30m=vol_accel_1m_over_30m,
        spread_over_atr=spread_over_atr,
        depth_usd=depth_usd,
    )


def _rsi(closes, period):
    deltas = np.diff(closes)
    up = deltas.clip(min=0)
    down = (-deltas).clip(min=0)
    ru = up[-period:].mean() if len(up) >= period else up.mean() if len(up) > 0 else 0
    rd = (
        down[-period:].mean() if len(down) >= period else down.mean() if len(down) > 0 else 1e-9
    )
    rs = ru / max(rd, 1e-9)
    return 100 - 100 / (1 + rs)


def _atr(kl):
    trs = []
    for i in range(1, len(kl)):
        _, _, h, l, c_prev, *_ = kl[i - 1]
        _, o, h1, l1, c, *_ = kl[i]
        h = float(h1)
        l = float(l1)
        c_prev = float(c_prev)
        trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
    return sum(trs) / len(trs) if trs else 0.0
