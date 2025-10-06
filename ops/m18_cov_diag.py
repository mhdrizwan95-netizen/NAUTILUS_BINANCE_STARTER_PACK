#!/usr/bin/env python3
"""
ops/m18_cov_diag.py — M18 Covariance Diagnostics

Produces comprehensive diagnostics for multi-symbol covariance-aware allocations:

- Real-time covariance matrix heatmap
- Eigenvalue spectrum analysis (correlation structure)
- Historical allocation weights over time
- Portfolio variance tracking

Usage:
    python ops/m18_cov_diag.py

Outputs:
    - data/processed/m18/cov_matrix.png
    - data/processed/m18/eigen_spectrum.png
    - data/processed/m18/alloc_weights.csv
    - data/processed/m18/covariance_metrics.json
"""

import os
import json
import argparse
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Import from our strategies
import sys
sys.path.insert(0, os.path.dirname(__file__))

from strategies.hmm_policy.covariance_allocator import CovarianceAllocator, get_covariance_allocator

# Setup
OUT_DIR = "data/processed/m18"
os.makedirs(OUT_DIR, exist_ok=True)
plt.style.use('default')

# For demo, create synthetic return data across multiple symbols
def generate_synthetic_returns(n_symbols=4, n_periods=1000, base_vol=0.02):
    """Generate synthetic correlated returns for demonstration."""
    symbols = [f'SYMBOL{i}' for i in range(n_symbols)]

    # Create base correlation structure
    base_corr = 0.3
    corr_matrix = np.full((n_symbols, n_symbols), base_corr)
    np.fill_diagonal(corr_matrix, 1.0)

    # Add some specific correlations
    corr_matrix[0, 1] = 0.7  # High correlation between first two
    corr_matrix[2, 3] = 0.6  # Moderate correlation between last two

    # Generate correlated returns
    L = np.linalg.cholesky(corr_matrix)
    noise = np.random.normal(0, base_vol, (n_periods, n_symbols))
    returns = noise @ L.T

    # Add some regime shifts
    cut1, cut2 = n_periods//3, 2*n_periods//3

    # First regime: normal
    returns[:cut1] *= 1.0

    # Second regime: higher correlation
    returns[cut1:cut2] = returns[cut1:cut2] @ np.array([[1.5, 0.8, 0.2, 0.2],
                                                        [0.8, 1.5, 0.2, 0.2],
                                                        [0.2, 0.2, 1.0, 0.6],
                                                        [0.2, 0.2, 0.6, 1.0]])

    # Third regime: decoupled
    returns[cut2:] *= np.array([1.0, 1.0, 1.5, 1.5])  # Last two more volatile

    return symbols, returns

def create_covariance_heatmap(allocator: CovarianceAllocator):
    """Create covariance matrix heatmap."""
    corr_df = allocator.correlation_matrix()

    if corr_df.empty or corr_df.shape[0] < 2:
        print("No correlation data available for heatmap")
        return

    plt.figure(figsize=(10, 8))

    # Create mask for upper triangle
    mask = np.triu(np.ones_like(corr_df, dtype=bool))

    # Custom colormap centered at 0
    cmap = sns.diverging_palette(240, 10, as_cmap=True)

    sns.heatmap(corr_df, mask=mask, cmap=cmap, vmax=1, vmin=-1, center=0,
                square=True, linewidths=.5, cbar_kws={"shrink": .8},
                annot=True, fmt=".2f")

    plt.title('M18 Covariance Matrix Heatmap\n(Last 500 Period Rolling Window)', fontsize=14, pad=20)
    plt.tight_layout()

    output_path = os.path.join(OUT_DIR, "cov_matrix.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved covariance heatmap: {output_path}")

def create_eigen_analysis_plot(allocator: CovarianceAllocator):
    """Create eigenvalue spectrum plot."""
    eigen_info = allocator.eigen_analysis()

    if not eigen_info.get('eigenvalues'):
        print("No eigenvalue data available")
        return

    eigenvalues = np.array(eigen_info['eigenvalues'])
    explained_var = np.array(eigen_info['explained_var_ratio'])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    # Eigenvalue spectrum
    ax1.plot(range(1, len(eigenvalues) + 1), eigenvalues, 'bo-', linewidth=2, markersize=6)
    ax1.set_xlabel('Eigenvalue Index')
    ax1.set_ylabel('Eigenvalue')
    ax1.set_title('Eigenvalue Spectrum\n(Covariance Matrix Structure)')
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color='k', linestyle='--', alpha=0.3)

    # Scree plot (explained variance)
    ax2.plot(range(1, len(explained_var) + 1), explained_var * 100, 'ro-', linewidth=2, markersize=6)
    ax2.set_xlabel('Principal Component')
    ax2.set_ylabel('Explained Variance (%)')
    ax2.set_title('Explained Variance by Component')
    ax2.grid(True, alpha=0.3)

    # Add cumulative line
    cum_var = np.cumsum(explained_var) * 100
    ax2_twin = ax2.twinx()
    ax2_twin.plot(range(1, len(cum_var) + 1), cum_var, 'g--', linewidth=2, alpha=0.7)
    ax2_twin.set_ylabel('Cumulative Explained Variance (%)', color='green')

    plt.suptitle('M18 Eigenvalue Analysis\n(Correlation Structure Decomposition)', fontsize=14)
    plt.tight_layout()

    output_path = os.path.join(OUT_DIR, "eigen_spectrum.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved eigenvalue analysis: {output_path}")

def create_weights_simulation_plot():
    """Simulate and plot allocation weights over time."""
    # Create synthetic data
    symbols, returns = generate_synthetic_returns(n_symbols=4, n_periods=1200)
    print(f"Simulated returns for {len(symbols)} symbols: {symbols}")

    # Initialize allocator
    allocator = CovarianceAllocator(window=500, target_var=0.0001)

    # Simulate over time
    weights_history = []

    for i in range(len(returns)):
        # Update with returns for each symbol
        for j, symbol in enumerate(symbols):
            ret = returns[i, j]
            allocator.update(symbol, ret)

        # Record weights after sufficient data
        if i >= 100:  # Wait for some history
            weights = allocator.weights()
            weights_history.append(weights.copy())

    # Convert to DataFrame for plotting
    if not weights_history:
        print("No weights history collected")
        return

    df_weights = pd.DataFrame(weights_history)
    df_weights.fillna(0, inplace=True)

    # Create time series plot
    plt.figure(figsize=(14, 8))

    colors = plt.cm.tab10(np.linspace(0, 1, len(symbols)))
    for i, symbol in enumerate(symbols):
        color = colors[i]
        plt.plot(df_weights.index, df_weights.get(symbol, 0),
                label=symbol, color=color, linewidth=2, alpha=0.8)

    plt.xlabel('Time Period')
    plt.ylabel('Allocation Weight')
    plt.title('M18 Covariance-Based Weight Allocation Over Time\n(4 Symbols with Regime Shifts)')
    plt.legend()
    plt.grid(True, alpha=0.3)

    # Add regime annotation
    time_periods = len(df_weights)
    cut1, cut2 = time_periods//4, 2*time_periods//4
    plt.axvline(x=cut1, color='red', linestyle='--', alpha=0.7, label='Regime Changes')
    plt.axvline(x=cut2, color='red', linestyle='--', alpha=0.7)

    # Add portfolio variance annotation
    port_vars = []
    for i in range(len(weights_history)):
        allocator_temp = CovarianceAllocator(window=500, target_var=0.0001)
        # Re-simulate to this point for variance calculation
        for j in range(min(500, i+1)):
            for k, symbol in enumerate(symbols):
                idx = max(0, i - j)
                allocator_temp.update(symbol, returns[idx, k])

        if len(allocator_temp.return_buffers[symbols[0]]) > 50:
            port_vars.append(allocator_temp.portfolio_variance())
        else:
            port_vars.append(0)

    ax2 = plt.twinx()
    ax2.plot(df_weights.index, np.array(port_vars) * 1e4, 'k--', alpha=0.6, label='Port Var (bps²)')
    ax2.set_ylabel('Portfolio Variance (×10⁴)')
    ax2.legend(loc='upper right')

    plt.tight_layout()

    output_path = os.path.join(OUT_DIR, "weight_simulation.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved weight simulation: {output_path}")

    # Export final weights to CSV
    csv_path = os.path.join(OUT_DIR, "alloc_weights.csv")
    df_weights.to_csv(csv_path, index_label='period')
    print(f"Saved allocation weights: {csv_path}")

def save_covariance_metrics(allocator: CovarianceAllocator):
    """Save covariance metrics to JSON."""
    debug_state = allocator.debug_state()

    # Add additional metrics
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "analysis_type": "m18_covariance_diagnostics",
        "allocator_config": {
            "window": allocator.window,
            "target_var": allocator.target_var,
            "min_periods": allocator.min_periods
        },
        "runtime_state": debug_state,
        "correlation_matrix": allocator.correlation_matrix().to_dict() if not allocator.correlation_matrix().empty else {},
        "eigen_analysis": allocator.eigen_analysis()
    }

    metrics_path = os.path.join(OUT_DIR, "covariance_metrics.json")
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2, default=str)

    print(f"Saved covariance metrics: {metrics_path}")
    print(f"\n📊 Key Metrics:")
    print(f"   Symbols tracked: {debug_state.get('symbols_tracked', [])}")
    print(f"   Portfolio variance: {debug_state.get('portfolio_variance', 0)*1e4:.3f} bps²")
    print(f"   Target variance: {debug_state.get('target_variance', 0)*1e4:.3f} bps²")
    print(f"   Correlation available: {debug_state.get('correlation_matrix_available', False)}")

def main():
    parser = argparse.ArgumentParser(description="M18 Covariance Diagnostics")
    parser.add_argument("--demo", action="store_true", help="Use synthetic data for demonstration")

    args = parser.parse_args()

    print("🔬 M18 Covariance-Aware Risk Allocation Diagnostics")
    print("=" * 60)

    if args.demo:
        print("Using synthetic multi-symbol data for demonstration...")
        # Note: In production, you'd get this from the real allocator instance
        # For demo, we'll create a fresh one and populate it with synthetic data

        # Create demo allocator
        allocator = CovarianceAllocator(window=500, target_var=0.0001)

        # Generate synthetic data
        symbols, returns = generate_synthetic_returns(n_symbols=4, n_periods=800)

        # Populate allocator with returns
        for i in range(len(returns)):
            for j, symbol in enumerate(symbols):
                allocator.update(symbol, returns[i, j])

        print(f"Populated allocator with {len(returns)} periods across {len(symbols)} symbols")

    else:
        print("Using global allocator instance...")
        # In production, get the real allocator that's been running
        allocator = get_covariance_allocator()

        if not allocator.return_buffers:
            print("No data in global allocator. Run some trades first or use --demo")
            print("Expected usage:")
            print("  1. Run trading system with covariance allocator enabled")
            print("  2. Accumulate returns via allocator.update() calls")
            print("  3. Run diagnostics to visualize results")
            return 1

    # Generate all diagnostic outputs
    print("\n📈 Generating covariance diagnostics...")

    try:
        create_covariance_heatmap(allocator)
        create_eigen_analysis_plot(allocator)
        create_weights_simulation_plot()
        save_covariance_metrics(allocator)

        print("\n✅ M18 covariance diagnostics completed!")
        print(f"All outputs saved to: {OUT_DIR}/")

    except Exception as e:
        print(f"❌ Diagnostics failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
