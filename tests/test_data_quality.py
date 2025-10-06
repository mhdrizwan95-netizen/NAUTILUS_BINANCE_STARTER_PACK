from backtests.data_quality import check_row
def test_nan_caught():
    issues, _ = check_row(0, {"ts_ns":1, "bid_px": float("nan"), "ask_px": 1.0}, None)
    assert "nan_px" in issues
