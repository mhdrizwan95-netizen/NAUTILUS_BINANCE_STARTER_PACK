#!/usr/bin/env python3
import pickle, numpy as np, pandas as pd

with open("engine/models/hmm_policy.pkl", "rb") as f:
    model = pickle.load(f)

# Mock some data - you could point to actual CSV here
import numpy as np

np.random.seed(42)
prices = 50000 + np.random.randn(1000) * 1000  # BTC-like prices
volumes = 100 + np.random.rand(1000) * 200  # BTC-like volumes


# Make the rolling features to test
def _rolling_features(
    price: np.ndarray, volume: np.ndarray, window: int
) -> pd.DataFrame:
    pass

    # Simple 1-step returns
    rets = np.zeros_like(price)
    rets[1:] = (price[1:] - price[:-1]) / np.where(price[:-1] == 0, 1e-12, price[:-1])

    s = pd.DataFrame({"price": price, "volume": volume, "ret": rets})
    s["vola"] = s["ret"].rolling(20, min_periods=2).std().fillna(0.0)

    # VWAP deviation over 'window'
    vw_num = (s["price"] * s["volume"]).rolling(window, min_periods=1).sum()
    vw_den = (s["volume"]).rolling(window, min_periods=1).sum().replace(0, 1.0)
    vwap = vw_num / vw_den
    s["vwap_dev"] = (s["price"] - vwap) / vwap.replace(0, 1.0)

    # z-score of price over 30
    roll = s["price"].rolling(30, min_periods=2)
    mean30 = roll.mean()
    std30 = roll.std().replace(0, 1.0)
    s["zprice30"] = (s["price"] - mean30) / std30

    # volume spike ratio vs last 20
    vol_ma20 = s["volume"].rolling(20, min_periods=1).mean().replace(0, 1.0)
    s["vol_spike"] = s["volume"] / vol_ma20

    # latest return as in runtime features
    s["ret_last"] = s["ret"]

    feats = s[["ret_last", "vola", "vwap_dev", "zprice30", "vol_spike"]].copy()
    feats = feats.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return feats


# Generate features like training does
feats = _rolling_features(prices, volumes, window=120)
feats = feats.iloc[120:].reset_index(drop=True)  # Drop warmup
X = feats.values[-5:]  # Test with last 5 rows

# Run predictions
probs = model.predict_proba(X)
print("Last 5 regime probabilities:")
print("=" * 40)
for i, p in enumerate(probs):
    print("05d")

# Check that probabilities sum to ~1 (basic sanity)
for i, p in enumerate(probs):
    total_prob = np.sum(p)
    print("05d")
    assert np.isclose(total_prob, 1.0, atol=1e-5), f"Probs don't sum to 1: {total_prob}"

print("\n✅ Model loaded and produces valid regime probabilities!")
