#!/usr/bin/env python3
"""
Automatic Backtest Artifact Uploader
-----------------------------------
Registers a trained model (weights, metrics, plots, config) with OPS registry
so it appears instantly in /strategy/ui leaderboard.

This creates the closed-loop: research → registry → governance → deployment
"""

import hashlib
import json
import shutil
import subprocess  # nosec B404 - intentional shell out to scp/rsync
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REGISTRY_PATH = Path("ops/strategy_registry.json")
ARTIFACT_ROOT = Path("ops/model_artifacts")


def utc_now():
    """Return ISO timestamp for consistent logging."""
    return datetime.now(tz=timezone.utc).isoformat()


def compute_hash(path: Path) -> str:
    """Compute SHA-1 hash of file for integrity verification."""
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()[:8]
    except Exception as e:
        print(f"[Uploader] Hash computation failed: {e}")
        return "nohash"


def load_registry() -> Dict[str, Any]:
    """Load existing strategy registry or create new one."""
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception as e:
            print(f"[Uploader] Registry load failed: {e}")

    return {"current_model": None, "promotion_log": []}


def save_registry(registry: Dict[str, Any]) -> None:
    """Atomically save registry to disk."""
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2))
    tmp.replace(REGISTRY_PATH)


def get_git_sha(short: bool = True) -> str:
    """Get current git commit hash for experiment tracking."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        if short:
            cmd.insert(1, "--short")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=".")
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"[Uploader] Git SHA retrieval failed: {result.stderr}")
            return f"nogit_{int(time.time())}"
    except Exception as e:
        print(f"[Uploader] Git SHA error: {e}")
        return f"nogit_{int(time.time())}"


def register_model(
    tag: str,
    weights_path: str,
    metrics_path: Optional[str] = None,
    plot_path: Optional[str] = None,
    config_path: Optional[str] = None,
    extra_metrics: Optional[Dict[str, Any]] = None,
    register_type: str = "backtest",
    description: str = "",
):
    """
    Copy artifacts into ops/model_artifacts/<tag>/ and register metadata.

    Args:
        tag: Model identifier (e.g., 'hmm_v2')
        weights_path: Path to trained model weights
        metrics_path: Optional path to metrics.json
        plot_path: Optional path to backtest plot
        config_path: Optional path to hyperparameters
        extra_metrics: Direct metrics dict if not from file
        register_type: 'backtest', 'training', 'exploration'
        description: Human-readable description
    """

    print(f"[Uploader] Registering model '{tag}' ({register_type})...")

    # Load existing registry
    registry = load_registry()

    # Create artifact storage directory
    model_dir = ARTIFACT_ROOT / tag
    model_dir.mkdir(parents=True, exist_ok=True)

    # Copy weights (required)
    weights = Path(weights_path)
    if not weights.exists():
        raise FileNotFoundError(f"Weights file not found: {weights_path}")

    dest_weights = model_dir / weights.name
    shutil.copy2(weights, dest_weights)

    # Compute integrity hash
    config_hash = compute_hash(dest_weights)

    # Copy metrics file or use provided dict
    dest_metrics = None
    metrics_data = None

    if metrics_path and Path(metrics_path).exists():
        mfile = Path(metrics_path)
        dest_metrics = model_dir / mfile.name
        shutil.copy2(mfile, dest_metrics)
        # Load metrics for initial scoring
        try:
            metrics_data = json.loads(mfile.read_text())
        except Exception:
            metrics_data = extra_metrics or {}

    if not dest_metrics and extra_metrics:
        dest_metrics = model_dir / "metrics.json"
        dest_metrics.write_text(json.dumps(extra_metrics, indent=2))
        metrics_data = extra_metrics

    # Copy optional plot
    dest_plot = None
    if plot_path and Path(plot_path).exists():
        pfile = Path(plot_path)
        dest_plot = model_dir / pfile.name
        shutil.copy2(pfile, dest_plot)

    # Copy optional config
    if config_path and Path(config_path).exists():
        shutil.copy2(config_path, model_dir / Path(config_path).name)

    # Create registry entry
    entry = {
        "sharpe": metrics_data.get("backtest_sharpe") if metrics_data else None,
        "drawdown": metrics_data.get("max_drawdown") if metrics_data else None,
        "realized": 0.0,  # Will be filled by live trading
        "trades": metrics_data.get("total_trades") if metrics_data else 0,
        "version": 1,
        "artifact_path": str(dest_weights),
        "metrics_path": str(dest_metrics or ""),
        "backtest_plot": str(dest_plot or ""),
        "config_hash": config_hash,
        "last_promotion": utc_now(),
        "register_type": register_type,
        "description": description or f"Registered via {register_type}",
        "git_sha": get_git_sha(),
        "registered_at": utc_now(),
    }

    # Initialize model if it doesn't exist
    if tag not in registry:
        registry[tag] = entry
    else:
        # Update existing but preserve some live statistics
        existing = registry[tag]
        for key, value in entry.items():
            if key in [
                "sharpe",
                "drawdown",
                "realized",
                "trades",
                "version",
                "artifact_path",
                "metrics_path",
                "backtest_plot",
                "config_hash",
                "last_promotion",
                "register_type",
                "description",
                "git_sha",
                "registered_at",
            ]:
                existing[key] = value
        registry[tag] = existing

    save_registry(registry)

    print(f"[Uploader] Model '{tag}' registered successfully. Hash: {config_hash}")
    return {
        "model_tag": tag,
        "registry_path": str(REGISTRY_PATH),
        "artifact_dir": str(model_dir),
        "hash": config_hash,
        "ready_for_promotion": True,
    }


def list_registered_models() -> Dict[str, Any]:
    """Return summary of all registered models."""
    registry = load_registry()

    summary = {
        "current_model": registry.get("current_model"),
        "total_registered": len(
            [k for k in registry.keys() if k not in ["current_model", "promotion_log"]]
        ),
        "models": {},
    }

    for tag, stats in registry.items():
        if tag in ["current_model", "promotion_log"]:
            continue
        summary["models"][tag] = {
            "sharpe": stats.get("sharpe"),
            "version": stats.get("version", 1),
            "registered": stats.get("registered_at"),
            "has_artifacts": bool(stats.get("artifact_path")),
            "has_plot": bool(stats.get("backtest_plot")),
        }

    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Register a trained/backtested model into OPS governance registry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Register a trained model
  python ops/backtest_uploader.py \\
    --tag hmm_v3 \\
    --weights outputs/models/hmm_v3/weights.pkl \\
    --metrics outputs/models/hmm_v3/metrics.json \\
    --plot outputs/models/hmm_v3/backtest.png

  # Register with inline metrics (no files)
  python ops/backtest_uploader.py \\
    --tag ensemble_quick_test \\
    --weights models/quick_test.pkl \\
    --extra-metrics '{"backtest_sharpe": 1.34, "max_drawdown": 3.2}'

  # Register exploratory model with git integration
  python ops/backtest_uploader.py \\
    --tag exploration_sma_fast \\
    --weights experiments/sma_fast/weights.pt \\
    --type exploration \\
    --description "Fast SMA crossover variant for testing"
        """,
    )

    parser.add_argument("--tag", required=True, help="Model tag identifier")
    parser.add_argument("--weights", required=True, help="Path to model weights file")
    parser.add_argument("--metrics", help="Path to metrics.json file")
    parser.add_argument("--plot", help="Path to backtest plot image")
    parser.add_argument("--config", help="Path to hyperparameters config")
    parser.add_argument(
        "--type",
        choices=["backtest", "training", "exploration"],
        default="backtest",
        help="Registration type",
    )
    parser.add_argument("--description", help="Human-readable description")
    parser.add_argument("--extra-metrics", type=json.loads, help="Extra metrics as JSON string")

    args = parser.parse_args()

    try:
        result = register_model(
            tag=args.tag,
            weights_path=args.weights,
            metrics_path=args.metrics,
            plot_path=args.plot,
            config_path=args.config,
            extra_metrics=args.extra_metrics,
            register_type=args.type,
            description=args.description,
        )

        # Success summary
        print("\n" + "=" * 60)
        print("🎉 MODEL REGISTRATION SUCCESSFUL!")
        print(f"   Tag: {result['model_tag']}")
        print(f"   Hash: {result['hash']}")
        print(f"   Registry: {result['registry_path']}")
        print(f"   Artifacts: {result['artifact_dir']}")
        print("\n📊 Check governance dashboard:")
        print("   http://localhost:8002/strategy/ui")
        print("   http://localhost:8002/strategy/leaderboard")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ REGISTRATION FAILED: {e}")
        exit(1)
