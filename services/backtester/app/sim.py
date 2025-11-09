from collections.abc import Callable
from typing import Any

import pandas as pd

from .ml import HMMModel


class Trade:
    def __init__(self, ts_open, ts_close, side, entry, exit, qty, symbol, params, features):
        self.ts_open = ts_open
        self.ts_close = ts_close
        self.side = side
        self.entry = float(entry)
        self.exit = float(exit)
        self.qty = float(qty)
        self.symbol = symbol
        self.params = params
        self.features = features
        self.cost = 0.0

    @property
    def pnl(self):
        gross = (self.exit - self.entry) * (self.qty if self.side == "long" else -self.qty)
        return gross - self.cost


class PrequentialSim:
    """
    Simulates online (test-then-train) evaluation.
    At each step t:
      1) Strategy decides using model trained up to t-1 (no peeking).
      2) We observe bar t, execute trade logic and close intrabar (toy) or after N bars.
      3) We update the model with the bar t (or every RETRAIN cadence).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        bar_minutes: int,
        retrain_every_min: int,
        exactly_once: bool,
        cost_fn: Callable,
    ):
        self.df = df
        self.bar_minutes = bar_minutes
        self.retrain_every_min = retrain_every_min
        self.exactly_once = exactly_once
        self.cost_fn = cost_fn
        self.strategies: list[Any] = []
        self.model = HMMModel()  # embedded copy; in prod, call ml_service
        self.last_train_ts = None
        self.trades: list[Trade] = []

    def add_strategy(self, strat):
        strat.bind_model(self.model)
        self.strategies.append(strat)

    def _should_retrain(self, now_ts: pd.Timestamp) -> bool:
        if self.last_train_ts is None:
            return True
        delta = (now_ts - self.last_train_ts).total_seconds() / 60.0
        return delta >= self.retrain_every_min

    def _train_until(self, ts: pd.Timestamp):
        # Train using bars strictly BEFORE ts (prequential). If EXACTLY_ONCE,
        # use only bars that have not yet been used in previous trainings.
        if self.last_train_ts is None:
            end = ts
            self.model.train(self.df[:end])
            self.last_train_ts = ts
            return
        if self._should_retrain(ts):
            start = self.last_train_ts if self.exactly_once else None
            self.model.train(self.df[:ts], start_ts=start)
            self.last_train_ts = ts

    def run(self):
        df = self.df
        # Prime: initial train on earliest window (if enough bars)
        for idx, row in df.iterrows():
            now = idx
            # 1) Make decisions with model trained up to now (previous train)
            for s in self.strategies:
                order = s.decide(now, row)
                if order is not None:
                    trade = self._execute(order, now, row)
                    self.trades.append(trade)
                    # report outcome back into strategy (for param learning)
                    s.observe_outcome(trade)
            # 2) Update model with bar now (or on cadence)
            if self._should_retrain(now):
                self._train_until(now)
        # Final train to include tail (optional)
        return {"n_bars": len(df)}, self.trades

    def _execute(self, order: dict[str, Any], now, row) -> Trade:
        # Toy execution: enter at 'close' and exit next bar at 'close'
        # Qty proportional to edge (bounded).
        edge = float(order.get("edge", 0.0))
        qty = max(0.0, min(1.0, abs(edge)))  # [0,1]
        side = "long" if edge >= 0 else "short"
        entry = row["close"]
        # in this toy, exit at same close (intrabar) so pnl=0 before costs; real engine would manage positions
        exitp = row["close"]
        trade = Trade(
            now,
            now,
            side,
            entry,
            exitp,
            qty,
            order["symbol"],
            order.get("params", {}),
            order.get("features", {}),
        )
        trade.cost = self.cost_fn(trade)
        return trade
