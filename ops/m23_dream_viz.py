#!/usr/bin/env python3
"""
ops/m23_dream_viz.py — Dream Performance Visualization

Analyzes archived dream cycles and generates performance analytics and evolution plots.
Provides insight into how ancestral models perform across different dream scenarios
and reveals learning patterns through offline exploration.

Generates dream_timeline.png showing:
- Dream frequency and success rates over time
- Performance evolution across market regimes
- Accuracy and P&L distributions from simulated scenarios
- Ancestral model performance comparisons
"""

import json
import os
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configure matplotlib for publication quality
plt.style.use('default')
plt.rcParams.update({'font.size': 10, 'figure.dpi': 160, 'savefig.bbox': 'tight'})

DREAM_ARCHIVE = os.path.join("data", "dreams")
OUTPUT_DIR = os.path.join("data", "dreams")

def load_dream_history() -> Optional[pd.DataFrame]:
    """
    Load complete dream history for analysis and visualization.

    Returns:
        DataFrame containing all dream session data, or None if no data
    """
    if not os.path.exists(DREAM_ARCHIVE):
        print("[M23] 🛌 No dream archive found - no dreams to visualize")
        return None

    dream_records = []

    for filename in os.listdir(DREAM_ARCHIVE):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(DREAM_ARCHIVE, filename), 'r') as f:
                    dream_data = json.load(f)
                    dream_records.append(dream_data)
            except Exception as e:
                print(f"[M23] ⚠️ Failed to load dream {filename}: {e}")

    if not dream_records:
        print("[M23] 📭 No dream records found in archive")
        return None

    # Convert to DataFrame
    df = pd.DataFrame(dream_records)

    # Standardize timestamp column
    for ts_col in ['timestamp', 'cycle_timestamp']:
        if ts_col in df.columns:
            df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors='coerce')
            if df[ts_col].notna().sum() > 0:  # Has valid timestamps
                df['timestamp_dt'] = df[ts_col]
                break

    # Fallback timestamp creation
    if 'timestamp_dt' not in df.columns:
        df['timestamp_dt'] = datetime.utcnow()
        print("[M23] ℹ️ Using current timestamp for dreams without proper timestamping")

    # Sort by time
    df = df.sort_values('timestamp_dt').reset_index(drop=True)

    # Extract performance metrics with safe defaults
    df['accuracy_score'] = df.apply(
        lambda row: row.get('accuracy_score', 0.0) if pd.notna(row.get('accuracy_score')) else 0.0,
        axis=1
    )
    df['simulated_pnl'] = df.apply(
        lambda row: row.get('simulated_pnl', 0.0) if pd.notna(row.get('simulated_pnl')) else 0.0,
        axis=1
    )
    df['market_regime'] = df.apply(
        lambda row: row.get('market_regime', 'unknown'), axis=1
    )
    df['status'] = df.apply(
        lambda row: row.get('status', 'unknown'), axis=1
    )

    # Extract ancestral generation info
    df['ancestral_generation'] = df.apply(
        lambda row: row.get('ancestral_generation', 'unknown'), axis=1
    )

    print(f"[M23] 📊 Loaded {len(df)} dream records for analysis")
    return df

def create_dream_timeline(df: pd.DataFrame, output_path: str) -> None:
    """
    Create main dream timeline visualization showing performance evolution.

    Args:
        df: DataFrame with dream history
        output_path: Path to save visualization
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Filter successful dreams for analysis
    successful_dreams = df[df['status'] == 'success'].copy()
    if len(successful_dreams) == 0:
        print("[M23] ℹ️ No successful dreams to visualize")
        return

    # Set up figure with dual axes
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[2, 1])

    # Top plot: Performance over time
    scatter_colors = {
        'normal': '#1f77b4',    # Blue
        'volatile': '#ff7f0e',  # Orange
        'trending': '#2ca02c',  # Green
        'chaos': '#d62728',     # Red
        'unknown': '#7f7f7f'    # Gray
    }

    # Plot P&L and accuracy over time
    for regime in successful_dreams['market_regime'].unique():
        regime_data = successful_dreams[successful_dreams['market_regime'] == regime]
        color = scatter_colors.get(regime, scatter_colors['unknown'])

        ax1.scatter(regime_data['timestamp_dt'], regime_data['simulated_pnl'] * 100,
                   color=color, alpha=0.7, s=50, label=f'{regime} P&L')
        ax1.scatter(regime_data['timestamp_dt'], regime_data['accuracy_score'] * 100,
                   color=color, alpha=0.5, s=30, marker='^', label=f'{regime} Accuracy')

    ax1.set_ylabel('Performance (% or bps)')
    ax1.set_title('Dream Performance Timeline: Ancestral Model Evaluation in Synthetic Markets',
                 fontsize=14, fontweight='bold')
    ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax1.grid(True, alpha=0.3)

    # Format x-axis dates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    fig.autofmt_xdate()

    # Bottom plot: Success rate over time (rolling window)
    dream_success = df.set_index('timestamp_dt')['status'].map({'success': 1, 'error': 0})

    if len(dream_success) > 5:
        rolling_success = dream_success.rolling('2h').mean()
        ax2.plot(rolling_success.index, rolling_success * 100, 'g-', linewidth=2)
        ax2.fill_between(rolling_success.index, 0, rolling_success * 100, alpha=0.2, color='green')
        ax2.set_ylim(0, 100)
    else:
        # Not enough data for rolling average
        ax2.bar(range(len(dream_success)), dream_success.map({1: 100, 0: 10}),
               color=['green' if x == 1 else 'red' for x in dream_success])
        ax2.set_xticks(range(len(dream_success)))
        ax2.set_xticklabels([f"D{d+1}" for d in range(len(dream_success))], rotation=45)

    ax2.set_ylabel('Success Rate (%)')
    ax2.set_xlabel('Dream Timeline')
    ax2.set_title(f'Dream Success Rate (Total Dreams: {len(df)}, Success: {len(successful_dreams)})')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, bbox_inches='tight')
    print(f"[M23] ✅ Dream timeline saved: {output_path}")

def create_performance_distributions(df: pd.DataFrame, output_path: str) -> None:
    """
    Create performance distribution analysis by market regime.

    Args:
        df: DataFrame with dream data
        output_path: Path to save distribution plot
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    successful_dreams = df[df['status'] == 'success']
    if len(successful_dreams) < 3:
        print("[M23] ℹ️ Insufficient data for distribution analysis")
        return

    # Set up subplot grid
    regimes = successful_dreams['market_regime'].unique()
    fig, axes = plt.subplots(2, len(regimes), figsize=(4*len(regimes), 8))
    if len(regimes) == 1:
        axes = axes.reshape(-1, 1)

    regime_colors = {
        'normal': '#1f77b4', 'volatile': '#ff7f0e',
        'trending': '#2ca02c', 'chaos': '#d62728', 'unknown': '#7f7f7f'
    }

    for i, regime in enumerate(regimes):
        regime_data = successful_dreams[successful_dreams['market_regime'] == regime]
        color = regime_colors.get(regime, regime_colors['unknown'])

        # Accuracy distribution
        axes[0, i].hist(regime_data['accuracy_score'] * 100, bins=10,
                       alpha=0.7, color=color, edgecolor='black')
        axes[0, i].set_title(f'{regime.title()} Markets\nAccuracy Distribution')
        axes[0, i].set_xlabel('Model Accuracy (%)')
        axes[0, i].set_ylabel('Frequency')
        axes[0, i].grid(True, alpha=0.3)

        # P&L distribution (convert to basis points)
        axes[1, i].hist(regime_data['simulated_pnl'] * 10000, bins=10,
                       alpha=0.7, color=color, edgecolor='black')
        axes[1, i].set_title('Simulated P&L Distribution')
        axes[1, i].set_xlabel('P&L (basis points)')
        axes[1, i].set_ylabel('Frequency')
        axes[1, i].grid(True, alpha=0.3)

        # Add mean lines
        mean_accuracy = regime_data['accuracy_score'].mean() * 100
        mean_pnl = regime_data['simulated_pnl'].mean() * 10000

        axes[0, i].axvline(mean_accuracy, color='red', linestyle='--', linewidth=2,
                          label=f'Mean: {mean_accuracy:.1f}%')
        axes[1, i].axvline(mean_pnl, color='red', linestyle='--', linewidth=2,
                          label=f'Mean: {mean_pnl:.0f}bps')

        axes[0, i].legend()
        axes[1, i].legend()

    plt.suptitle('Performance Distributions by Market Regime\n(Revealing Ancestral Strengths and Weaknesses)',
                fontsize=14, fontweight='bold', y=0.95)
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches='tight')
    print(f"[M23] ✅ Performance distributions saved: {output_path}")

def create_generational_insights(df: pd.DataFrame, output_path: str) -> None:
    """
    Create analysis of how different generations perform in dreams.

    Args:
        df: DataFrame with dream performance data
        output_path: Path to save generational analysis
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    successful_dreams = df[df['status'] == 'success']
    if len(successful_dreams['ancestral_generation'].unique()) < 2:
        print("[M23] ℹ️ Insufficient generational diversity for analysis")
        return

    # Group by generation and calculate averages
    gen_stats = successful_dreams.groupby('ancestral_generation').agg({
        'accuracy_score': ['mean', 'std', 'count'],
        'simulated_pnl': ['mean', 'std']
    }).round(4)

    # Flatten column names
    gen_stats.columns = ['_'.join(col).strip() for col in gen_stats.columns.values]

    # Create visualization
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Accuracy by generation
    gen_stats['accuracy_score_mean'].plot(kind='bar', ax=ax1,
                                         color='skyblue', alpha=0.8, yerr=gen_stats['accuracy_score_std'])
    ax1.set_ylabel('Mean Model Accuracy')
    ax1.set_title('Dream Performance by Ancestral Generation')
    ax1.set_xlabel('Generation')
    for i, count in enumerate(gen_stats['accuracy_score_count']):
        ax1.text(i, 0.02, f'n={count}', ha='center', va='bottom', rotation=90)
    ax1.grid(True, alpha=0.3)

    # P&L by generation
    gen_stats['simulated_pnl_mean'].plot(kind='bar', ax=ax2,
                                        color='salmon', alpha=0.8, yerr=gen_stats['simulated_pnl_std'])
    ax2.set_ylabel('Mean Simulated P&L')
    ax2.set_title('Profitability by Ancestral Generation')
    ax2.set_xlabel('Generation')
    ax2.axhline(y=0, color='red', linestyle='--', alpha=0.5)
    for i, count in enumerate(gen_stats['accuracy_score_count']):
        ax2.text(i, max(gen_stats['simulated_pnl_mean'].min()*0.8, -0.01),
                f'n={count}', ha='center', va='top', rotation=90)
    ax2.grid(True, alpha=0.3)

    plt.suptitle('Ancestral Generation Performance in Dream Simulations\n(Which Traits Survive the Test of Time?)')
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches='tight')
    print(f"[M23] ✅ Generational insights saved: {output_path}")

def generate_dream_insights_report(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate comprehensive insights report from dream history.

    Args:
        df: DataFrame with dream data

    Returns:
        Dictionary containing key insights and recommendations
    """
    report = {
        "total_dreams": len(df),
        "dream_success_rate": 0.0,
        "top_performing_regime": "unknown",
        "most_reliable_ancestor": "unknown",
        "performance_insights": [],
        "recommendations": []
    }

    successful_dreams = df[df['status'] == 'success']
    if len(successful_dreams) == 0:
        report["recommendations"].append("No successful dreams found. Check M21 memory vault for archivied models.")
        return report

    # Basic metrics
    report["dream_success_rate"] = len(successful_dreams) / len(df)

    # Find best regime
    regime_performance = successful_dreams.groupby('market_regime')['accuracy_score'].mean()
    if len(regime_performance) > 0:
        report["top_performing_regime"] = regime_performance.idxmax()

    # Find most reliable ancestor
    ancestor_performance = successful_dreams.groupby('ancestral_generation')['accuracy_score'].std()
    if len(ancestor_performance) > 0:
        # Lowest standard deviation = most consistent
        report["most_reliable_ancestor"] = ancestor_performance.idxmin()

    # Generate insights
    avg_performance = successful_dreams['accuracy_score'].mean()
    if avg_performance > 0.6:
        report["performance_insights"].append("High average accuracy suggests robust ancestral foundation")
    elif avg_performance < 0.5:
        report["performance_insights"].append("Low average accuracy indicates potential model quality issues")
        report["recommendations"].append("Consider retraining with additional reinforcement cycles")

    # Check for regime biases
    regime_counts = successful_dreams['market_regime'].value_counts()
    if regime_counts.max() / regime_counts.sum() > 0.7:
        report["performance_insights"].append("Dreams heavily biased toward single regime - diversify scenarios")

    return report

def main():
    """Generate all dream visualizations and analyses."""
    print("[M23] 🌙 Dream Visualization Engine activating...")

    # Load dream history
    df = load_dream_history()
    if df is None:
        print("[M23] 📭 No dream archive available for visualization")
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        # Main timeline visualization
        timeline_path = os.path.join(OUTPUT_DIR, "dream_timeline.png")
        create_dream_timeline(df, timeline_path)

        # Performance distributions
        if len(df[df['status'] == 'success']) >= 5:
            dist_path = os.path.join(OUTPUT_DIR, "dream_distributions.png")
            create_performance_distributions(df, dist_path)

        # Generational analysis
        if len(df['ancestral_generation'].unique()) > 1:
            gen_path = os.path.join(OUTPUT_DIR, "dream_generations.png")
            create_generational_insights(df, gen_path)

        # Generate insights report
        insights = generate_dream_insights_report(df)
        report_path = os.path.join(OUTPUT_DIR, "dream_insights.json")
        with open(report_path, 'w') as f:
            json.dump(insights, f, indent=2)
        print(f"[M23] 📋 Insights report saved: {report_path}")

        print(f"[M23] 🎨 Dream visualization complete! Generated plots in {OUTPUT_DIR}")
        print(".1f"
        if insights["performance_insights"]:
            print(f"[M23] 🔍 Key Insights: {len(insights['performance_insights'])} discoveries made")

    except Exception as e:
        print(f"[M23] ⚠️ Visualization error: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
