import numpy as np


def summarize(trades):
    if not trades:
        return {"net_pnl": 0.0, "sharpe": 0.0, "max_dd": 0.0, "n": 0}
    pnl = np.array([t.pnl for t in trades], dtype=float)
    net = float(pnl.sum())
    mu = pnl.mean()
    sd = pnl.std(ddof=1) if len(pnl) > 1 else 0.0
    sharpe = float(np.sqrt(252) * (mu / sd)) if sd > 0 else 0.0
    # equity curve & drawdown
    eq = pnl.cumsum()
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak).min() if len(eq) > 0 else 0.0
    return {"net_pnl": net, "sharpe": sharpe, "max_dd": float(dd), "n": int(len(pnl))}
