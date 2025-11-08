from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Perf:
    pnl: float
    sharpe: float
    maxdd: float
    n_trades: int
    turnover: float


def compute_perf(equity: pd.Series, trades: pd.DataFrame) -> Perf:
    ret = equity.pct_change().dropna()
    if ret.std() == 0:
        sharpe = 0.0
    else:
        sharpe = (ret.mean() / ret.std()) * np.sqrt(252 * 24 * 60)  # minute bars approx
    dd = (equity / equity.cummax() - 1.0).min() if not equity.empty else 0.0
    turnover = trades["notional"].abs().sum() if "notional" in trades.columns else 0.0
    return Perf(
        pnl=float(equity.iloc[-1] - equity.iloc[0]) if len(equity) > 0 else 0.0,
        sharpe=float(sharpe),
        maxdd=float(dd),
        n_trades=int(len(trades)),
        turnover=float(turnover),
    )
