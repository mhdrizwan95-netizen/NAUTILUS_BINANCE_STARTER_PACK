#!/usr/bin/env python3
"""
Model Governance Registry for HMM Trading Strategies

Usage:
  # Register a freshly trained model with backtest metrics
  python scripts/model_registry.py register \
      --model engine/models/hmm_policy.pkl \
      --symbol BTCUSDT \
      --train-metrics reports/backtest_BTCUSDT.json \
      --tag hmm_v1 \
      --notes "Baseline 3-regime model trained on Oct 2025 data"

  # Promote the best model to production
  python scripts/model_registry.py promote --tag hmm_v1

  # List all models in registry
  python scripts/model_registry.py list

  # Show details of a specific model
  python scripts/model_registry.py info --tag hmm_v1
"""

import argparse, json, time, shutil
from pathlib import Path
import sys

REGISTRY_PATH = Path("engine/models/registry.jsonl")
ACTIVE_LINK = Path("engine/models/active_hmm_policy.pkl")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_registry():
    """Read append-only registry file."""
    if not REGISTRY_PATH.exists():
        return []
    with open(REGISTRY_PATH, "r") as f:
        entries = []
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines but log
                    print(
                        f"Warning: Skipping malformed registry entry: {line[:50]}...",
                        file=sys.stderr,
                    )
        return entries


def _write_entry(entry: dict):
    """Append entry to registry."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _get_entry_by_tag(tag: str):
    """Find entry by tag."""
    entries = _read_registry()
    return next((e for e in entries if e.get("tag") == tag), None)


def cmd_register(args):
    """Register a model in the governance registry."""
    model_path = Path(args.model)
    if not model_path.exists():
        raise SystemExit(f"Model file does not exist: {model_path}")

    # Load train metrics if provided
    train_metrics = None
    if args.train_metrics:
        metrics_path = Path(args.train_metrics)
        if metrics_path.exists():
            try:
                with open(metrics_path, "r") as f:
                    train_metrics = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: Could not read metrics file: {e}", file=sys.stderr)
        else:
            print(f"Warning: Metrics file does not exist: {metrics_path}", file=sys.stderr)

    # Check for existing tag
    existing = _get_entry_by_tag(args.tag)
    if existing:
        print(
            f"Warning: Tag '{args.tag}' already exists. Registration will create duplicate.",
            file=sys.stderr,
        )

    entry = {
        "tag": args.tag,
        "model_path": str(model_path.resolve()),
        "symbol": args.symbol,
        "ts_registered": _now(),
        "notes": args.notes,
    }

    if train_metrics:
        entry["train_metrics"] = train_metrics

    _write_entry(entry)
    print(f"✅ Registered model '{args.tag}' at {model_path}")
    print(f"   Registry: {REGISTRY_PATH}")

    # Show key metrics if available
    if train_metrics:
        pnl = train_metrics.get("pnl_usd", "N/A")
        sharpe = train_metrics.get("Sharpe", "N/A")
        max_dd = train_metrics.get("max_drawdown_usd", "N/A")
        print(f"   Performance: PnL=${pnl}, Sharpe={sharpe}, MaxDD=${max_dd}")


def cmd_promote(args):
    """Promote a registered model to active production."""
    entry = _get_entry_by_tag(args.tag)
    if not entry:
        raise SystemExit(f"No model found with tag='{args.tag}'")

    src_path = Path(entry["model_path"])
    if not src_path.exists():
        raise SystemExit(f"Model file missing: {src_path}")

    dst_path = ACTIVE_LINK
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing link/file
    if dst_path.exists() or dst_path.is_symlink():
        dst_path.unlink()

    # Copy model to active location
    shutil.copy(src_path, dst_path)

    promote_entry = {
        "action": "promote",
        "promoted_tag": args.tag,
        "model_path_src": str(src_path),
        "model_path_dst": str(dst_path),
        "ts_promoted": _now(),
        "promoted_by": args.user or "unknown",
        "promote_reason": args.reason or f"Promoted {args.tag} to production",
    }

    _write_entry(promote_entry)
    print(f"🚀 Promoted '{args.tag}' to production")
    print(f"   Active model: {dst_path}")
    print(f"   Source: {src_path}")

    # Show registry update
    _show_registry_status()


def cmd_list(args):
    """List all registered models."""
    entries = _read_registry()
    if not entries:
        print("No models registered yet.")
        return

    # Filter for model registrations (not promote actions)
    models = [e for e in entries if "action" not in e]

    if not models:
        print("No model registrations found.")
        return

    print(f"{'Tag':<12} {'Symbol':<8} {'Registered':<20} {'Notes'}")
    print("-" * 70)

    for e in sorted(models, key=lambda x: x.get("ts_registered", ""), reverse=True):
        tag = e.get("tag", "")
        symbol = e.get("symbol", "")
        ts = e.get("ts_registered", "")
        notes = (e.get("notes", "") or "")[:40]

        # Highlight active model
        active_mark = " ← ACTIVE" if _is_active_model(e) else ""
        print(f"{tag:<12} {symbol:<8} {ts:<20} {notes}{active_mark}")


def cmd_info(args):
    """Show detailed info for a specific model."""
    entry = _get_entry_by_tag(args.tag)
    if not entry:
        raise SystemExit(f"No model found with tag='{args.tag}'")

    print(f"Model Details: {args.tag}")
    print("=" * 40)
    print(f"Symbol:        {entry.get('symbol', 'N/A')}")
    print(f"Registered:    {entry.get('ts_registered', 'N/A')}")
    print(f"Model Path:    {entry.get('model_path', 'N/A')}")
    print(f"Is Active:     {_is_active_model(entry)}")
    print(f"Notes:         {entry.get('notes', 'N/A')}")

    # Show training metrics if available
    metrics = entry.get("train_metrics")
    if metrics:
        print(f"\nTraining Performance:")
        print(f"  Symbol:      {metrics.get('symbol', 'N/A')}")
        print(f"  PnL:         ${metrics.get('pnl_usd', 0):.2f}")
        print(f"  Sharpe:      {metrics.get('Sharpe', 0):.3f}")
        print(f"  Win Rate:    {metrics.get('winrate', 0):.1%}")
        print(f"  Max Drawdown: ${metrics.get('max_drawdown_usd', 0):.2f}")
        print(f"  Trades:      {metrics.get('trades', 0)}")


def _is_active_model(entry):
    """Check if a model is currently active."""
    if not ACTIVE_LINK.exists():
        return False
    try:
        active_path = ACTIVE_LINK.resolve()
        model_path = Path(entry["model_path"]).resolve()
        return active_path == model_path
    except (OSError, KeyError):
        return False


def _show_registry_status():
    """Show current registry status."""
    entries = _read_registry()
    models = [e for e in entries if "action" not in e]
    promotes = [e for e in entries if e.get("action") == "promote"]

    print(f"\nRegistry Status:")
    print(f"  Total Models: {len(models)}")
    print(f"  Total Promotions: {len(promotes)}")
    if promotes:
        latest_promote = max(promotes, key=lambda x: x.get("ts_promoted", ""))
        promoted_tag = latest_promote.get("promoted_tag", "unknown")
        promoted_ts = latest_promote.get("ts_promoted", "unknown")
        print(f"  Last Promotion: {promoted_tag} @ {promoted_ts}")
    if ACTIVE_LINK.exists():
        print(f"  Active Model: {ACTIVE_LINK}")
    else:
        print("  Active Model: None (engine will use default)")


def main():
    parser = argparse.ArgumentParser(description="HMM Model Governance Registry")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Register command
    reg_parser = subparsers.add_parser("register", help="Register a new model")
    reg_parser.add_argument("--model", required=True, help="Path to trained HMM model .pkl file")
    reg_parser.add_argument("--symbol", required=True, help="Trading symbol for this model")
    reg_parser.add_argument(
        "--train-metrics", help="Path to backtest JSON file with performance metrics"
    )
    reg_parser.add_argument(
        "--tag", required=True, help="Unique tag for this model (e.g., 'hmm_v1')"
    )
    reg_parser.add_argument("--notes", default="", help="Optional notes about this model")

    # Promote command
    prom_parser = subparsers.add_parser("promote", help="Promote model to production")
    prom_parser.add_argument("--tag", required=True, help="Model tag to promote")
    prom_parser.add_argument("--user", help="Who is promoting (for audit)")
    prom_parser.add_argument("--reason", help="Reason for promotion")

    # List command
    list_parser = subparsers.add_parser("list", help="List all registered models")

    # Info command
    info_parser = subparsers.add_parser("info", help="Show model details")
    info_parser.add_argument("--tag", required=True, help="Model tag to inspect")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Execute command
    if args.command == "register":
        cmd_register(args)
    elif args.command == "promote":
        cmd_promote(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "info":
        cmd_info(args)


if __name__ == "__main__":
    main()
