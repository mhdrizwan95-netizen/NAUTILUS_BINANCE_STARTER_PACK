#!/usr/bin/env python3
"""
ops/m21_memory_viz.py — Evolutionary Lineage Visualization

Generates performance evolution plots and trend analysis from the fossil record.
Creates visual representations of the organism's learning journey and fitness landscape.

Produces lineage_graph.png with dual-axis charts showing:
- Performance metrics over evolutionary time
- Generation boundary markers
- Improvement trendlines
- Ancestral comparison overlays
"""

import json
import os
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import pandas as pd
from typing import Dict, Optional

# Configure matplotlib for better output
plt.style.use("default")
plt.rcParams.update({"font.size": 10, "figure.dpi": 160})

LINEAGE_INDEX = os.path.join("data", "memory_vault", "lineage_index.json")
OUTPUT_DIR = os.path.join("data", "memory_vault")


def load_lineage_data() -> Optional[pd.DataFrame]:
    """
    Load fossil records from the lineage index.

    Returns:
        DataFrame with evolutionary history, or None if no data available
    """
    if not os.path.exists(LINEAGE_INDEX):
        print(f"❌ Lineage index not found: {LINEAGE_INDEX}")
        return None

    try:
        with open(LINEAGE_INDEX, "r") as f:
            data = json.load(f)

        models = data.get("models", [])
        if not models:
            print("ℹ️  No models found in lineage index")
            return None

        # Convert to DataFrame
        df = pd.DataFrame(models)

        # Ensure archived_at column exists, create if missing
        if "archived_at" not in df.columns and "timestamp" in df.columns:
            df["archived_at"] = df["timestamp"]
        elif "archived_at" not in df.columns:
            # Fallback: generate timestamps if neither exists
            now = datetime.utcnow()
            df["archived_at"] = [now.isoformat()] * len(df)

        # Convert timestamp strings to datetime
        df["archived_at"] = pd.to_datetime(df["archived_at"], utc=True, errors="coerce")
        df = df.dropna(subset=["archived_at"])  # Drop rows with invalid timestamps

        # Sort by time
        df = df.sort_values("archived_at").reset_index(drop=True)

        # Extract performance metrics (handle missing data gracefully)
        df["pnl_last"] = df.apply(
            lambda row: row.get("performance_snapshot", {}).get("pnl_last", 0), axis=1
        )
        df["winrate_last"] = df.apply(
            lambda row: row.get("performance_snapshot", {}).get("winrate_last", 0),
            axis=1,
        )

        # Extract generation types for color coding
        df["generation_type"] = df.apply(
            lambda row: row.get("generation_type", "unknown"), axis=1
        )

        print(f"📊 Loaded {len(df)} fossil records from lineage")
        return df

    except Exception as e:
        print(f"❌ Error loading lineage data: {e}")
        return None


def assign_generation_colors(generation_types: pd.Series) -> Dict[str, str]:
    """
    Assign distinct colors to different generation types.

    Args:
        generation_types: Series of generation type labels

    Returns:
        Dictionary mapping generation types to colors
    """
    unique_types = generation_types.unique()
    colors = [
        "#1f77b4",  # blue - M15 (calibration foundation)
        "#ff7f0e",  # orange - M16 (reinforcement learning)
        "#2ca02c",  # green - M17 (hierarchical regime detection)
        "#d62728",  # red - M18 (covariance coordination)
        "#9467bd",  # purple - M19 (meta-scheduling intelligence)
        "#8c564b",  # brown - M20 (reflexive resilience)
        "#e377c2",  # pink - M21+ (advanced memory systems)
        "#7f7f7f",  # gray - unknown/legacy
    ]

    color_map = {}
    for i, gen_type in enumerate(unique_types):
        color_map[gen_type] = colors[min(i, len(colors) - 1)]

    return color_map


def create_lineage_graph(df: pd.DataFrame, output_path: str) -> None:
    """
    Generate the main evolutionary lineage visualization.

    Creates a dual-axis plot showing performance evolution over time.

    Args:
        df: DataFrame containing fossil records
        output_path: Path to save the visualization
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Set up the figure with dual y-axes
    fig, ax1 = plt.subplots(figsize=(15, 8))

    # Primary axis: P&L performance
    color_map = assign_generation_colors(df["generation_type"])

    # Plot P&L trend line
    ax1.plot(
        df["archived_at"],
        df["pnl_last"],
        linewidth=2,
        alpha=0.7,
        color="#1f77b4",
        marker="o",
        markersize=6,
        markerfacecolor="white",
        label="Realized P&L (USD)",
    )

    # Color-code generation markers
    for gen_type, group in df.groupby("generation_type"):
        color = color_map.get(gen_type, "#7f7f7f")
        ax1.scatter(
            group["archived_at"],
            group["pnl_last"],
            color=color,
            s=80,
            alpha=0.8,
            edgecolors="white",
            linewidth=2,
            label=f"{gen_type} generations",
        )

    ax1.set_ylabel("Realized P&L (USD)", fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.set_title(
        "Evolutionary Lineage & Performance Trajectory\nTrading Organism M15→M21",
        fontsize=14,
        fontweight="bold",
        pad=20,
    )

    # Secondary axis: Winrate performance
    ax2 = ax1.twinx()
    ax2.plot(
        df["archived_at"],
        df["winrate_last"],
        linewidth=2,
        alpha=0.7,
        color="#ff7f0e",
        marker="s",
        markersize=6,
        markerfacecolor="white",
        label="Win Rate (%)",
    )

    ax2.set_ylabel("Win Rate (%)", fontsize=12, fontweight="bold")
    ax2.set_ylim(bottom=max(0, ax2.get_ylim()[0]))  # Keep winrate above 0

    # Format x-axis dates nicely
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M"))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())

    # Rotate and align the tick labels so they look better
    fig.autofmt_xdate()

    # Add trend lines if we have enough data
    if len(df) >= 3:
        # Linear trend for P&L
        pnl_trend = ax1.axhline(
            y=df["pnl_last"].mean(),
            color="#1f77b4",
            linestyle="--",
            alpha=0.5,
            label=f'Avg P&L: ${df["pnl_last"].mean():.2f}',
        )

        # Linear trend for winrate
        winrate_trend = ax2.axhline(
            y=df["winrate_last"].mean(),
            color="#ff7f0e",
            linestyle="--",
            alpha=0.5,
            label=f'Avg Winrate: {df["winrate_last"].mean():.1f}%',
        )

    # Create unified legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        bbox_to_anchor=(0.02, 0.98),
        framealpha=0.9,
        ncol=2,
    )

    # Add evolutionary milestone markers
    add_evolutionary_markers(ax1, df)

    # Add summary statistics in a text box
    add_summary_stats(df, ax1)

    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    print(f"✅ Lineage graph saved: {output_path}")


def add_evolutionary_markers(ax, df: pd.DataFrame) -> None:
    """
    Add vertical lines marking major evolutionary transitions.

    Args:
        ax: Matplotlib axis to add markers to
        df: DataFrame containing generation data
    """
    milestones = {
        "M15": ("Calibration Foundation", "🔧"),
        "M16": ("Reinforcement Learning", "🧠"),
        "M17": ("Hierarchical Regimes", "🌊"),
        "M18": ("Covariance Coordination", "🔗"),
        "M19": ("Meta-Intelligence", "🎯"),
        "M20": ("Resilience & Reflexes", "🛡️"),
        "M21": ("Memory & Ancestry", "🧬"),
    }

    used_milestones = df["generation_type"].unique()
    ylim = ax.get_ylim()

    for gen_type in sorted(used_milestones):
        if gen_type in milestones:
            # Find first occurrence of this generation type
            gen_data = df[df["generation_type"] == gen_type].iloc[0]
            timestamp = gen_data["archived_at"]

            ax.axvline(x=timestamp, color="red", linestyle="-.", alpha=0.3, linewidth=2)

            # Add milestone label
            label, emoji = milestones[gen_type]
            ax.annotate(
                f"{emoji} {gen_type}\n{label}",
                xy=(timestamp, ylim[1]),
                xytext=(timestamp, ylim[1] + (ylim[1] - ylim[0]) * 0.02),
                ha="center",
                va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="red", alpha=0.1),
                fontsize=9,
                fontweight="bold",
            )


def add_summary_stats(df: pd.DataFrame, ax) -> None:
    """
    Add summary statistics box to the visualization.

    Args:
        ax: Matplotlib axis to add stats to
        df: DataFrame containing performance data
    """
    basic_stats = {
        "Total Generations": len(df),
        "Evolution Span": (
            f"{((df['archived_at'].max() - df['archived_at'].min()).total_seconds() / 86400):.0f} days"
            if len(df) > 1
            else "N/A"
        ),
        "P&L Range": f"${df['pnl_last'].min():.2f} → ${df['pnl_last'].max():.2f}",
        "Winrate Range": f"{df['winrate_last'].min():.1f}% → {df['winrate_last'].max():.1f}%",
        "Net Improvement": f"P&L: ${df['pnl_last'].iloc[-1] - df['pnl_last'].iloc[0]:+.2f} | Winrate: {df['winrate_last'].iloc[-1] - df['winrate_last'].iloc[0]:+.1f}pp",
    }

    # Create stats text
    stats_text = "Evolutionary Summary:\n" + "\n".join(
        [f"{k}: {v}" for k, v in basic_stats.items()]
    )

    # Add as text box in upper right
    ax.text(
        0.98,
        0.98,
        stats_text,
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment="top",
        horizontalalignment="right",
        bbox=dict(
            boxstyle="round,pad=0.5", facecolor="white", alpha=0.8, edgecolor="gray"
        ),
        multialignment="left",
    )


def create_performance_distribution(df: pd.DataFrame, output_path: str) -> None:
    """
    Create a distribution analysis of performance metrics.

    Args:
        df: DataFrame containing performance data
        output_path: Path to save the distribution plot
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # P&L Distribution
    ax1.hist(df["pnl_last"], bins=20, alpha=0.7, color="#1f77b4", edgecolor="black")
    ax1.axvline(
        df["pnl_last"].mean(),
        color="red",
        linestyle="--",
        linewidth=2,
        label=f'Mean: ${df["pnl_last"].mean():.2f}',
    )
    ax1.axvline(
        df["pnl_last"].median(),
        color="green",
        linestyle="--",
        linewidth=2,
        label=f'Median: ${df["pnl_last"].median():.2f}',
    )
    ax1.set_xlabel("Realized P&L (USD)")
    ax1.set_ylabel("Frequency")
    ax1.set_title("P&L Performance Distribution")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Winrate Distribution
    ax2.hist(df["winrate_last"], bins=20, alpha=0.7, color="#ff7f0e", edgecolor="black")
    ax2.axvline(
        df["winrate_last"].mean(),
        color="red",
        linestyle="--",
        linewidth=2,
        label=f'Mean: {df["winrate_last"].mean():.1f}%',
    )
    ax2.axvline(
        df["winrate_last"].median(),
        color="green",
        linestyle="--",
        linewidth=2,
        label=f'Median: {df["winrate_last"].median():.1f}%',
    )
    ax2.set_xlabel("Win Rate (%)")
    ax2.set_ylabel("Frequency")
    ax2.set_title("Winrate Performance Distribution")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.suptitle("Performance Metric Distributions Across Evolutionary Lineage")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    print(f"✅ Performance distribution saved: {output_path}")


def create_generation_type_summary(df: pd.DataFrame, output_path: str) -> None:
    """
    Create summary visualization of generation type performance.

    Args:
        df: DataFrame containing generation and performance data
        output_path: Path to save the summary plot
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if df["generation_type"].nunique() <= 1:
        print("ℹ️  Insufficient generation diversity for generation summary")
        return

    # Group by generation type
    gen_stats = (
        df.groupby("generation_type")
        .agg({"pnl_last": ["mean", "max", "count"], "winrate_last": ["mean", "max"]})
        .round(2)
    )

    # Flatten column names
    gen_stats.columns = ["_".join(col).strip() for col in gen_stats.columns.values]

    # Create visualization
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Mean P&L by generation
    gen_stats["pnl_last_mean"].plot(kind="bar", ax=ax1, color="#1f77b4", alpha=0.7)
    ax1.set_ylabel("Mean Realized P&L (USD)")
    ax1.set_title("Average P&L Performance by Generation Type")
    ax1.grid(True, alpha=0.3, axis="y")

    # Mean winrate by generation
    gen_stats["winrate_last_mean"].plot(kind="bar", ax=ax2, color="#ff7f0e", alpha=0.7)
    ax2.set_ylabel("Mean Win Rate (%)")
    ax2.set_title("Average Winrate Performance by Generation Type")
    ax2.grid(True, alpha=0.3, axis="y")

    plt.suptitle(
        "Generation Type Performance Comparison\nWhich evolutionary stages drove improvement?"
    )
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    print(f"✅ Generation summary saved: {output_path}")

    # Also print table to console
    print("\n📋 Generation Performance Summary:")
    print(gen_stats.to_string())


def main():
    """Generate all lineage visualizations."""
    print("🖼️  M21 Lineage Visualizer: Generating evolutionary plots...")

    # Load lineage data
    df = load_lineage_data()
    if df is None or len(df) == 0:
        print("❌ No lineage data available for visualization")
        return

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        # Main lineage graph
        lineage_path = os.path.join(OUTPUT_DIR, "lineage_graph.png")
        create_lineage_graph(df, lineage_path)

        # Performance distribution
        if len(df) >= 5:  # Only if we have enough data
            dist_path = os.path.join(OUTPUT_DIR, "performance_distributions.png")
            create_performance_distribution(df, dist_path)

        # Generation comparison
        if len(df) >= 3 and df["generation_type"].nunique() > 1:
            gen_path = os.path.join(OUTPUT_DIR, "generation_performance.png")
            create_generation_type_summary(df, gen_path)

        print(f"\n✅ Visualization complete! Check {OUTPUT_DIR}/ for generated plots.")

    except Exception as e:
        print(f"❌ Error during visualization: {e}")
        return


if __name__ == "__main__":
    main()
