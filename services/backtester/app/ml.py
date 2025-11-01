import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from hmmlearn.hmm import GaussianHMM


class HMMModel:
    def __init__(self, n_states: int = 4):
        self.n_states = n_states
        self.scaler = None
        self.hmm = None
        self.trained_until = None

    def _prep(self, df: pd.DataFrame):
        close = df["close"].astype(float)
        logret = np.log(close).diff().dropna()
        X = logret.values.reshape(-1, 1).astype(np.float64)
        return X, logret.index

    def train(self, df: pd.DataFrame, start_ts=None):
        if start_ts is not None and self.trained_until is not None:
            df = df[df.index > self.trained_until]
        X, _ = self._prep(df)
        if len(X) < 500:
            return
        self.scaler = StandardScaler()
        Xs = self.scaler.fit_transform(X)
        self.hmm = GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42,
        )
        self.hmm.fit(Xs)
        self.trained_until = df.index.max()

    def regime_edge(self, row) -> float:
        # Use only last point; in real code, use a small recent window
        if self.hmm is None or self.scaler is None:
            return 0.0
        x = np.array([[0.0]], dtype=float)  # placeholder zero logret intrabar
        proba = self.hmm.predict_proba(self.scaler.transform(x))[0]
        # crude edge proxy: trend-up minus trend-down states if you map them; here we use first-last
        return float(proba[0] - proba[-1])
