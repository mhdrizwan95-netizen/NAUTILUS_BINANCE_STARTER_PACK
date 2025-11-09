#!/usr/bin/env python3
"""
One-shot capital rebalance runner.

Usage examples:
  python ops/rebalance.py --offline
  python ops/rebalance.py --live --write --output /tmp/allocation.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from ops import capital_allocator


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """Load capital policy JSON with a friendly fallback."""
    policy_path = path or capital_allocator.POLICY_PATH
    policy = capital_allocator.load_json(
        policy_path,
        {
            "refresh_sec": 30,
            "base_equity_frac": 0.2,
            "min_quota_usd": 250.0,
            "max_quota_usd": 25000.0,
            "step_up_pct": 0.15,
            "step_down_pct": 0.20,
            "sharpe_promote": 1.0,
            "sharpe_demote": 0.3,
            "cooldown_sec": 900,
            "enabled": ["stable_model", "canary_model"],
            "allocation_mode": "dynamic",
        },
    )
    return policy


async def run_rebalance(live: bool, policy_path: Path | None) -> dict[str, Any]:
    """Execute a single allocation cycle, returning the raw result."""
    policy = load_policy(policy_path)

    if live:
        metrics = await capital_allocator.fetch_live_metrics()
    else:
        metrics = capital_allocator.fetch_registry_fallback()

    # simulate_allocation_cycle expects metrics dict; avoid extra fetch
    result = await capital_allocator.simulate_allocation_cycle(policy, metrics)
    return result


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    """Lightweight summary for CLI output."""
    detail = {
        "equity_usd": round(result["equity"], 2),
        "total_allocated": round(result["total_allocated"], 2),
        "models": {},
    }
    for model, alloc in result["target_allocations"].items():
        detail["models"][model] = {
            "target_quota": round(alloc["target_quota"], 2),
            "decision": alloc["decision"],
            "sharpe": round(alloc.get("sharpe", 0.0), 3),
            "reason": alloc.get("reason"),
            "next_update": alloc.get("next_update"),
        }
    return detail


def write_allocations(result: dict[str, Any], path: Path) -> None:
    """Persist allocation state in the same shape as the allocator loop."""
    payload = {
        "capital_quota_usd": result["final_quotas"],
        "updated_at": {
            model: alloc["last_update"] for model, alloc in result["target_allocations"].items()
        },
        "equity_usd": result["equity"],
        "ts": result["simulation_ts"],
        "details": result["target_allocations"],
    }
    capital_allocator.save_json(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single capital rebalance cycle.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Fetch live metrics from OPS_METRICS_URL (default: use registry fallback).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist the resulting allocations to ops/capital_allocations.json.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        help="Override policy path (defaults to ops/capital_policy.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the full JSON result for downstream tooling.",
    )
    args = parser.parse_args()

    result = asyncio.run(run_rebalance(args.live, args.policy))
    summary = summarise(result)

    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True))

    if args.write:
        write_allocations(result, capital_allocator.ALLOCATIONS_PATH)


if __name__ == "__main__":
    main()
