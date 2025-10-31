
import pandas as pd

def embargo_split(df: pd.DataFrame, embargo: int = 0):
    """
    Returns (train_idx, val_idx) with an optional embargo in rows.
    For SIM we rely on ml_service to enforce its own purging, but this utility
    is provided for local models if you plug them in.
    """
    n = len(df)
    split = int(n*0.8)
    train = list(range(0, max(0, split-embargo)))
    val = list(range(split, n))
    return train, val
