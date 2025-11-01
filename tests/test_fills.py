from backtests.fills import fill_price, slip_bp


def test_slip_bounds():
    s = slip_bp(
        "BUY",
        spread_bp=10,
        vol_bp=20,
        depth_ratio=0.5,
        p=None or __import__("backtests.fills").fills.FillParams(),
    )
    assert 0.05 <= s <= 8.0


def test_fill_monotonic():
    # higher vol/spread/depth -> worse price for BUY
    from backtests.fills import FillParams

    mid = 50000
    bid = 49990
    ask = 50010
    qty = 0.01
    hist = [float(mid)] * 200
    p_lo = fill_price("BUY", mid, bid, ask, 5, 5, qty, 1.0, hist, FillParams())
    p_hi = fill_price("BUY", mid, bid, ask, 50, 50, qty, 5.0, hist, FillParams())
    assert p_hi >= p_lo
