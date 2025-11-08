#!/usr/bin/env python3
"""
Auto-promotion controller for the HMM model registry.

Compares the latest registered model’s Sharpe and drawdown
with the currently promoted one and promotes only if better.

Usage:
  python scripts/auto_promote_if_better.py \
      --metric sharpe \
      --min-improve 0.05
"""

import json, os, math, argparse, shutil, sys
from pathlib import Path

# Import from model_registry
sys.path.append(str(Path(__file__).parent))
from model_registry import _read_registry, _get_entry_by_tag, REGISTRY_PATH, ACTIVE_LINK


def _metric(entry, metric):
    """Extract metric value safely."""
    try:
        tm = entry.get("train_metrics", {})
        if metric == "pnl_usd":
            return float(tm.get("pnl_usd", 0))
        elif metric == "sharpe":
            return float(tm.get("Sharpe", 0))
        elif metric.lower() == "max_drawdown_usd":
            return float(tm.get("max_drawdown_usd", 0))
        elif metric == "winrate":
            return float(tm.get("winrate", 0))
        else:
            return float(tm.get(metric, 0))
    except (KeyError, ValueError, TypeError):
        return 0.0


def _summary(entry):
    """Format summary string for display."""
    tm = entry.get("train_metrics", {})
    tag = entry.get("tag", "unknown")
    sharpe = tm.get("Sharpe", "N/A")
    drawdown = tm.get("max_drawdown_usd", "N/A")
    pnl = tm.get("pnl_usd", "N/A")
    return "20"


def _get_current_active():
    """Find the currently active model from registry."""
    if not ACTIVE_LINK.exists():
        return None

    try:
        active_realpath = os.path.realpath(ACTIVE_LINK)
        entries = _read_registry()
        for e in entries:
            if "action" not in e:  # Skip promotion actions
                if os.path.realpath(e["model_path"]) == active_realpath:
                    return e
    except (OSError, KeyError):
        pass
    return None


def _is_better(latest_metrics, current_metrics, metric, min_improve):
    """Determine if latest model is better based on metric."""
    latest_val = _metric({"train_metrics": latest_metrics}, metric)
    current_val = _metric({"train_metrics": current_metrics}, metric)

    if metric.lower() in ["sharpe", "pnl_usd", "winrate"]:
        # Higher is better
        improvement = latest_val - current_val
        return improvement >= min_improve
    elif metric.lower() == "max_drawdown_usd":
        # Lower is better (less negative drawdown)
        improvement = current_val - latest_val  # Positive if improved
        return improvement >= min_improve
    else:
        return False


def _promote_model(tag, reason="Auto-promotion based on metric improvement"):
    """Promote model to active status."""
    from model_registry import cmd_promote

    args = argparse.Namespace(tag=tag, user="auto_promoter", reason=reason)
    cmd_promote(args)


def main():
    ap = argparse.ArgumentParser(
        description="Auto-promote models that demonstrate statistical improvement"
    )
    ap.add_argument(
        "--metric",
        default="sharpe",
        choices=["sharpe", "pnl_usd", "max_drawdown_usd", "winrate"],
        help="Metric to compare for promotion decision",
    )
    ap.add_argument(
        "--min-improve",
        type=float,
        default=0.05,
        help="Minimum fractional improvement required (e.g., 0.05 = 5%%)",
    )
    args = ap.parse_args()

    if not REGISTRY_PATH.exists():
        print("❌ No registry file found. Run registry commands first.")
        return 1

    entries = _read_registry()
    if not entries:
        print("❌ No registry entries found.")
        return 1

    # Find latest registered model (not promotion actions)
    model_entries = [e for e in entries if "action" not in e]

    if not model_entries:
        print("❌ No model registrations found.")
        return 1

    latest = model_entries[-1]
    current = _get_current_active()

    metric = args.metric

    # Handle no current active model case
    if not current and len(model_entries) >= 1:
        print(".1f")
        latest_metrics = latest.get("train_metrics", {})
        metric_val = _metric(latest, metric)
        print(f"🚀 Auto-promoting the only available model '{latest['tag']}'")
        _promote_model(latest["tag"], f"Auto-promotion - first model: {metric}={metric_val}")
        return 0

    if not current:
        print("❌ Could not identify currently active model.")
        return 1

    # Compare models
    current_metrics = current.get("train_metrics", {})
    latest_metrics = latest.get("train_metrics", {})

    print("📊 Model Comparison:")
    print(f"  Current: {_summary(current)}")
    print(f"  Latest : {_summary(latest)}")

    if current["tag"] == latest["tag"]:
        print("✅ Latest model is already active - no action needed.")
        return 0

    better = _is_better(latest_metrics, current_metrics, metric, args.min_improve)

    if better:
        latest_val = _metric(latest, metric)
        current_val = _metric(current, metric)
        improvement = latest_val - current_val

        # Special formatting for drawdown (lower is better)
        if metric.lower() == "max_drawdown_usd":
            improvement = current_val - latest_val

        print("✅ Auto-promotion criteria met!")
        print(f"   {metric.upper()} improved by {improvement:.3f}")

        reason = f"Auto-promotion: {metric} improved by {improvement:.3f} (> {args.min_improve})"
        _promote_model(latest["tag"], reason)

        print("🚀 Auto-promotion completed successfully!")
        return 0

    else:
        print("❌ Auto-promotion criteria not met.")
        print(
            f"   {metric.upper()} did not improve sufficiently " f"(threshold: {args.min_improve})"
        )
        print("   Model remains in registry for manual review if desired.")
        return 0


if __name__ == "__main__":
    exit(main())
