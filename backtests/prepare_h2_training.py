#!/usr/bin/env python3
# backtests/prepare_h2_training.py — Prepare H2 training data from Parquet
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
import requests
import json

def load_parquet_ticks(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "ts_ns" not in df.columns:
        for c in ["ts","timestamp_ns","time_ns"]:
            if c in df.columns:
                df = df.rename(columns={c:"ts_ns"}); break
    if "ts_ns" not in df.columns:
        raise ValueError("Parquet must contain 'ts_ns'.")
    return df.sort_values("ts_ns").reset_index(drop=True)

def downsample_macro(data: pd.DataFrame, window_sec: int = 300) -> list:
    """Downsample to macro features per window."""
    from collections import deque
    import numpy as np

    macro_windows = []
    current_window = []
    window_start = None

    for _, row in data.iterrows():
        ts_ns = row["ts_ns"]
        if window_start is None:
            window_start = ts_ns
        if ts_ns - window_start >= window_sec * 1e9:
            # Process window
            mids = [r["mid"] for r in current_window if "mid" in r]
            spreads_bp = [r["spread_bp"] for r in current_window if "spread_bp" in r]
            if len(mids) > 30:
                # Compute macro features
                mids_arr = np.asarray(mids[-300:], dtype=np.float64)
                x = np.arange(len(mids_arr))
                slope = float(np.polyfit(x, mids_arr, 1)[0]) / max(np.mean(mids_arr), 1e-9)
                vol = float(np.median([r["vol_bp"] for r in current_window[-300:] if "vol_bp" in r])) if len([r for r in current_window if "vol_bp" in r]) > 10 else 0.0
                spr = float(np.median(spreads_bp[-300:])) if len(spreads_bp) > 10 else 0.0
                vol_q = float(np.quantile([r["vol_bp"] for r in current_window[-300:] if "vol_bp" in r], 0.75)) if len([r for r in current_window if "vol_bp" in r]) > 10 else 0.0
                spr_q = float(np.quantile(spreads_bp[-300:], 0.75)) if len(spreads_bp) > 10 else 0.0
                trend = float(np.sign(slope))
                macro_windows.append([vol, vol_q, spr, spr_q, slope, trend])

            # Reset for next window
            current_window = []
            window_start = ts_ns

        # Collect data point
        if all(k in row for k in ["mid", "spread_bp"]):
            current_window.append({
                "mid": float(row["mid"]) if "mid" in row else (row["bid_px"] + row["ask_px"]) / 2,
                "spread_bp": float(row.get("spread_bp", (row["ask_px"] - row["bid_px"]) / ((row["bid_px"] + row["ask_px"]) / 2) * 10000.0))
            })

    return macro_windows

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8010/train_h2")
    args = parser.parse_args()

    cfg = json.load(open(args.config))

    print(f"Loading {cfg['data_parquet']}")
    df = load_parquet_ticks(cfg["data_parquet"])

    # Compute mid/spread/free columns
    df["mid"] = (df["bid_px"] + df["ask_px"]) / 2
    df["spread_bp"] = (df["ask_px"] - df["bid_px"]) / df["mid"] * 10000.0
    df["vol_bp"] = 0.0  # compute rolling vol

    # Compute vol (rolling realization)
    from collections import deque
    mids_deque = deque(maxlen=600)
    vol_window = deque(maxlen=120)
    df = df.reset_index()  # ensure we can iterate

    for i, row in df.iterrows():
        mids_deque.append(row["mid"])
        if len(mids_deque) >= 2:
            arr = np.asarray(list(mids_deque), dtype=np.float64)[-120:]
            if len(arr) >= 2:
                rets = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
                if len(rets) >= 2:
                    vol_window.append(float(np.std(rets) * 1e4))
                    df.at[i, "vol_bp"] = np.mean(list(vol_window)) if vol_window else 0.0

    print(f"Processing {len(df)} rows -> macro features")
    macro_seqs = downsample_macro(df)
    print(f"Got {len(macro_seqs)} macro windows")

    # Simple macro clustering (k-means on macro features)
    if len(macro_seqs) < 10:
        print("Not enough macro data for training")
        return

    from sklearn.cluster import KMeans
    X_macro = np.asarray(macro_seqs, dtype=np.float32)
    kmeans = KMeans(n_clusters=min(3, len(macro_seqs)), random_state=42).fit(X_macro)
    macro_labels = kmeans.labels_

    # Bucket micro sequences by macro label
    micro_by_macro = {}
    # For bootstrap, use a sliding window through the data
    window_size = min(1000, len(df) // len(macro_seqs) if len(macro_seqs) > 0 else 1000)
    micro_len = min(9, len([c for c in df.columns if "feature" in c or c in ["mid","spread_bp","imbalance"]]))

    for i, label in enumerate(macro_labels):
        start_idx = i * window_size
        end_idx = min((i + 1) * window_size, len(df))
        if end_idx - start_idx < 50:
            continue
        window_df = df.iloc[start_idx:end_idx]

        # Extract micro feats (need to adapt based on actual feature computation)
        micro_seq = []
        for _, row in window_df.iterrows():
            # Assuming features are stored or computed; for demo, use basic ones
            feats = [row.get(f"feature_{j}", float(row["mid"])) for j in range(micro_len)]
            micro_seq.append(feats)

        if len(micro_seq) >= len(macro_seqs[0]) // 2:  # minimum length check
            if label not in micro_by_macro:
                micro_by_macro[label] = []
            micro_by_macro[label].append(micro_seq)

    payload = {
        "symbol": cfg["symbol"].split(".")[0],
        "macro_sequences": macro_seqs,
        "micro_sequences_by_macro": micro_by_macro,
        "n_macro": 3,
        "n_micro": 4
    }

    print(f"Posting to {args.url}")
    resp = requests.post(args.url, json=payload, timeout=30)
    print(f"Response: {resp.json()}")

if __name__ == "__main__":
    main()
