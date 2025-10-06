#!/usr/bin/env python3
"""
ops/m17_train_macro.py — Train Macro Regime HMM

Reads historical tick data from Parquet files and trains a macro regime classifier
based on volatility, volume, and market state features.

Usage:
    python ops/m17_train_macro.py --parquet data/processed/ticks.parquet --config backtests/configs/crypto_spot.yaml

Outputs:
    - ml_service/model_store/macro_regime_hmm.joblib
    - data/processed/m17/macro_regime_stats.json
    - data/processed/m17/macro_regime_diagnostics.png
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, Any

# Import the hierarchical HMM classes
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ml_service.hierarchical_hmm import MacroRegimeHMM
from backtests.data_quality import check_row
from strategies.hmm_policy.features import FeatureState, compute_features

OUT_DIR = "data/processed/m17"
MODEL_DIR = "ml_service/model_store"

def load_parquet_ticks(path: str) -> pd.DataFrame:
    """Load parquet tick data with timestamp normalization."""
    df = pd.read_parquet(path)

    # Handle different timestamp column names
    if "ts_ns" not in df.columns:
        for col in ["ts", "timestamp_ns", "time_ns", "timestamp"]:
            if col in df.columns:
                df = df.rename(columns={col: "ts_ns"})
                break

    if "ts_ns" not in df.columns:
        raise ValueError(f"Parquet must contain a timestamp column, found: {df.columns.tolist()}")

    # Convert timestamps if needed
    if df["ts_ns"].dtype != 'int64':
        try:
            df["ts_ns"] = pd.to_datetime(df["ts_ns"]).astype('int64')
        except:
            df["ts_ns"] = df["ts_ns"].astype('int64')

    df = df.sort_values("ts_ns").reset_index(drop=True)
    print(f"Loaded {len(df)} ticks from {path}")
    return df

def extract_macro_features(df: pd.DataFrame, window_sizes: list = [300, 1200, 3600]) -> pd.DataFrame:
    """
    Extract macro-level features for regime classification.

    Features include:
    - Realized volatility at multiple time scales
    - Volume spike indicators
    - Spread dynamics
    - Bid-ask imbalance
    - Trend strength
    - Drift detection
    """
    print(f"Extracting macro features from {len(df)} ticks...")

    features = []
    feature_columns = []

    # Basic market data preparation
    df = df.copy()
    if "mid" not in df.columns:
        df["mid"] = (df.get("bid_px", df["ask_px"]) + df.get("ask_px", df["bid_px"])) / 2
    if df["mid"].isna().all():
        print("Warning: Mid prices unavailable, skipping macro feature extraction")
        return pd.DataFrame()

    # Volatility features at different horizons
    returns = df["mid"].pct_change(fill_method=None).fillna(0)

    for window in window_sizes:
        vol_col = f"vol_{window}s"
        df[vol_col] = returns.rolling(window=window, min_periods=max(60, window//10)).std()
        feature_columns.append(vol_col)

        # Volume-normalized volatility if volume available
        if "volume" in df.columns:
            vol_norm = f"vol_norm_{window}s"
            avg_volume = df["volume"].rolling(window=window, min_periods=10).mean()
            df[vol_norm] = df[vol_col] / (avg_volume + 1e-8)
            feature_columns.append(vol_norm)

    # Spread-related features
    if "bid_px" in df.columns and "ask_px" in df.columns:
        spread_bp = "spread_bp"
        df[spread_bp] = ((df["ask_px"] - df["bid_px"]) / ((df["bid_px"] + df["ask_px"]) / 2)) * 10000
        feature_columns.append(spread_bp)

        # Spread volatility
        spread_vol = "spread_vol_300s"
        df[spread_vol] = df[spread_bp].rolling(window=300, min_periods=50).std()
        feature_columns.append(spread_vol)

    # Depth imbalance if available
    if "bid_sz" in df.columns and "ask_sz" in df.columns:
        imbalance = "depth_imbalance"
        total_depth = df["bid_sz"] + df["ask_sz"] + 1e-8
        df[imbalance] = (df["bid_sz"] - df["ask_sz"]) / total_depth
        feature_columns.append(imbalance)

    # Trend strength (momentum)
    for window in [300, 1200]:
        momentum = f"momentum_{window}s"
        df[momentum] = df["mid"] / df["mid"].shift(window) - 1
        feature_columns.append(momentum)

    # Volume spikes (relative to recent average)
    if "volume" in df.columns:
        for window in [300, 1200]:
            avg_vol = df["volume"].rolling(window=window, min_periods=50).mean()
            vol_spike = f"vol_spike_{window}s"
            df[vol_spike] = df["volume"] / (avg_vol + 1e-8)
            feature_columns.append(vol_spike)

    # Drift score (long-term mean reversion signal)
    for window in [3600, 7200]:
        drift = f"drift_{window}s"
        rolling_mean = df["mid"].rolling(window=window, min_periods=100).mean()
        rolling_std = df["mid"].rolling(window=window, min_periods=100).std()
        df[drift] = (df["mid"] - rolling_mean) / (rolling_std + 1e-8)
        feature_columns.append(drift)

    # Clean up NaN values (forward fill, then backward fill)
    df_features = df[feature_columns].fillna(method='ffill').fillna(method='bfill')

    # Drop any remaining NaN rows
    df_features = df_features.dropna()

    print(f"Extracted {len(df_features.columns)} macro features for {len(df_features)} time points")
    print(f"Feature columns: {df_features.columns.tolist()}")

    return df_features

def train_macro_hmm(features_df: pd.DataFrame, n_states: int = 3) -> MacroRegimeHMM:
    """
    Train the macro regime HMM.

    Args:
        features_df: DataFrame with macro features
        n_states: Number of regimes to detect

    Returns:
        Trained MacroRegimeHMM
    """
    print(f"Training macro HMM with {len(features_df)} samples and {features_df.shape[1]} features")

    # Convert to numpy array
    X = features_df.values

    # Initialize and train model
    macro_hmm = MacroRegimeHMM(n_states=n_states)
    macro_hmm.fit(X)

    # Get predictions for the training data
    regimes = macro_hmm.predict(X)
    probs = macro_hmm.predict_proba(X) if hasattr(macro_hmm, 'predict_proba') else None

    print(f"Model trained successfully. Sample predictions:")
    unique, counts = np.unique(regimes, return_counts=True)
    for regime, count in zip(unique, counts):
        print(f"  {regime}: {count} observations ({count/len(regimes)*100:.1f}%)")

    return macro_hmm

def save_diagnostics(hmm: MacroRegimeHMM, features_df: pd.DataFrame) -> None:
    """Generate and save diagnostic plots and statistics."""
    os.makedirs(OUT_DIR, exist_ok=True)

    # Get predictions for plotting
    X = features_df.values
    regimes = hmm.predict(X)

    # Get regime statistics
    stats = hmm.get_regime_stats()

    # Save statistics
    stats_file = os.path.join(OUT_DIR, "macro_regime_stats.json")
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"Saved regime statistics to {stats_file}")

    # Create diagnostic plot
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("M17 Macro Regime HMM Diagnostics", fontsize=16)

    # Plot 1: Regime distribution over time
    ax1 = axes[0, 0]
    time_idx = range(len(regimes))

    # Create color map for regimes
    regime_colors = {'Calm': 'green', 'Trend': 'blue', 'Chaos': 'red'}
    colors = [regime_colors.get(r, 'gray') for r in regimes]

    ax1.scatter(time_idx, [1] * len(time_idx), c=colors, alpha=0.6, s=2)
    ax1.set_xlabel('Time Index')
    ax1.set_ylabel('Regime Indicator')
    ax1.set_title('Regime Classification Over Time')
    ax1.set_yticks([0, 1, 2])
    ax1.set_yticklabels(['0', '1', '2'])

    # Plot 2: Transition matrix heatmap
    ax2 = axes[0, 1]
    if 'regime_statistics' in stats:
        trans_matrix = np.zeros((hmm.n_states, hmm.n_states))
        regime_names = stats['regime_names']

        for i, regime_from in enumerate(regime_names):
            for j, regime_to in enumerate(regime_names):
                trans_matrix[i, j] = stats['regime_statistics'][regime_from]['transitions_from'][regime_to]

        im = ax2.imshow(trans_matrix, cmap='Blues', vmin=0, vmax=1)
        ax2.set_title('Regime Transition Matrix')
        ax2.set_xlabel('To Regime')
        ax2.set_ylabel('From Regime')
        ax2.set_xticks(range(len(regime_names)))
        ax2.set_yticks(range(len(regime_names)))
        ax2.set_xticklabels(regime_names)
        ax2.set_yticklabels(regime_names)
        plt.colorbar(im, ax=ax2)

    # Plot 3: Feature distributions by regime
    ax3 = axes[1, 0]
    if len(features_df.columns) > 0:
        feature_name = features_df.columns[0]  # Plot first feature
        for regime in np.unique(regimes):
            mask = regimes == regime
            color = regime_colors.get(regime, 'gray')
            ax3.hist(features_df.iloc[mask.array][feature_name].values,
                    bins=30, alpha=0.7, label=regime, color=color,
                    density=True)
    ax3.set_xlabel(f'{feature_name} (standardized)')
    ax3.set_ylabel('Density')
    ax3.set_title('Feature Distribution by Regime')
    ax3.legend()

    # Plot 4: Regime stability (consecutive runs)
    ax4 = axes[1, 1]
    consecutive_counts = []
    current_count = 1
    for i in range(1, len(regimes)):
        if regimes[i] == regimes[i-1]:
            current_count += 1
        else:
            consecutive_counts.append(current_count)
            current_count = 1
    consecutive_counts.append(current_count)

    ax4.hist(consecutive_counts, bins=range(1, max(consecutive_counts)+2),
             alpha=0.7, edgecolor='black')
    ax4.set_xlabel('Consecutive Observations')
    ax4.set_ylabel('Frequency')
    ax4.set_title('Regime Stability (Run Lengths)')

    plt.tight_layout()

    # Save plot
    plot_file = os.path.join(OUT_DIR, "macro_regime_diagnostics.png")
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved diagnostic plots to {plot_file}")

def main():
    parser = argparse.ArgumentParser(description="Train M17 Macro Regime HMM")
    parser.add_argument("--parquet", required=True, help="Path to tick data parquet file")
    parser.add_argument("--config", help="Config file (for symbol/data parameters)")
    parser.add_argument("--states", type=int, default=3, help="Number of macro regimes")
    parser.add_argument("--output", default=f"{MODEL_DIR}/macro_regime_hmm.joblib", help="Model output path")

    args = parser.parse_args()

    print(f"M17 Macro Regime HMM Training")
    print(f"Input: {args.parquet}")
    print(f"Regimes: {args.states}")

    try:
        # Load and preprocess data
        df = load_parquet_ticks(args.parquet)

        # Extract macro features
        macro_features = extract_macro_features(df)

        if len(macro_features) == 0:
            print("ERROR: No valid macro features extracted")
            return 1

        # Train model
        macro_hmm = train_macro_hmm(macro_features, args.states)

        # Save model
        os.makedirs(MODEL_DIR, exist_ok=True)
        macro_hmm.save(args.output)
        print(f"Saved trained model to {args.output}")

        # Generate diagnostics
        save_diagnostics(macro_hmm, macro_features)

        print("✅ M17 Macro Regime HMM training completed successfully")
        print(f"Model saved: {args.output}")
        print(f"Diagnostics: {OUT_DIR}")

        return 0

    except Exception as e:
        print(f"ERROR: Training failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
