def simple_cost_model(trade, cost_bps: float, slip_bps_per_vol: float):
    # Toy: cost proportional to notional and a volatility proxy in features (abs edge as vol stand-in)
    notional = trade.entry * trade.qty
    base = cost_bps * 1e-4 * notional
    slip = slip_bps_per_vol * 1e-4 * notional * abs(trade.features.get("vol", 0.01))
    return float(base + slip)
