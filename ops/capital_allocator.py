"""
Dynamic Capital Allocator - Live Performance-Based Budget Optimization

Autonomous capital reallocation engine that continuously optimizes strategy funding
based on real-time Sharpe ratios and risk-adjusted performance metrics.

Architecture:
- Live metrics fetching from Prometheus
- Sharpe-based promotion/demotion decisions
- Real-time quota adjustments with cooldowns
- Persistent state for restart resilience
- Safe fallbacks and circuit breakers
"""

from __future__ import annotations
import os
import json
import time
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any
import httpx


# Configuration paths
POLICY_PATH = Path("ops/capital_policy.json")
ALLOCATIONS_PATH = Path("ops/capital_allocations.json")
REGISTRY_PATH = Path("ops/strategy_registry.json")

# Metrics source
METRICS_URL = os.getenv("OPS_METRICS_URL", "http://localhost:8002/metrics")
EQUITY_METRIC = "portfolio_equity_usd"

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)


def load_json(path: Path, default: Dict = None) -> Dict:
    """Safe JSON file loading with fallback."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logging.warning(f"Failed to load {path}: {e}")
    return default or {}


def save_json(path: Path, data: Dict) -> None:
    """Save data to JSON file atomically."""
    try:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2))
        temp_path.replace(path)
    except Exception as e:
        logging.error(f"Failed to save {path}: {e}")


def parse_prometheus_metrics(metrics_text: str) -> Dict[str, Any]:
    """
    Parse Prometheus metrics text to extract equity and model performance data.

    Returns dict with 'portfolio_equity_usd' and 'models' keys.
    """
    parsed = {"portfolio_equity_usd": 0.0, "models": {}}

    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Portfolio equity
        if "portfolio_equity_usd" in line and not "{" in line:
            try:
                # Simple format: portfolio_equity_usd 50000.0
                value_part = line.split()[-1]
                parsed["portfolio_equity_usd"] = float(value_part)
            except (ValueError, IndexError):
                continue

        # Strategy Sharpe ratios (model-tagged)
        elif line.startswith("strategy_sharpe{") and "model=" in line:
            # strategy_sharpe{model="hmm_v4_canary"} 2.31
            parts = line.split("{", 1)
            if len(parts) != 2:
                continue
            parts[0]
            labels_part = parts[1].split("}")[0]
            value_part = parts[1].split("}")[1].strip()

            try:
                labels = parse_labels(labels_part)
                model = labels.get("model", "unknown")
                value = float(value_part)
                parsed["models"].setdefault(model, {})["sharpe"] = value
            except (ValueError, IndexError):
                continue

        # Realized PnL (for additional context)
        elif line.startswith("pnl_realized_total{") and "model=" in line:
            parts = line.split("{", 1)
            if len(parts) != 2:
                continue
            labels_part = parts[1].split("}")[0]
            value_part = parts[1].split("}")[1].strip()

            try:
                labels = parse_labels(labels_part)
                model = labels.get("model", "unknown")
                value = float(value_part)
                parsed["models"].setdefault(model, {})["realized_pnl"] = value
            except (ValueError, IndexError):
                continue

    return parsed


def parse_labels(labels_str: str) -> Dict[str, str]:
    """Parse Prometheus label string like 'model="hmm_v4"'."""
    labels = {}
    for kv in labels_str.split(","):
        kv = kv.strip()
        if "=" in kv:
            key, value = kv.split("=", 1)
            labels[key.strip()] = value.strip('"')
    return labels


async def fetch_live_metrics() -> Dict[str, Any]:
    """
    Fetch live metrics from OPS/Prometheus.

    Returns parsed metrics dict with fallback logic.
    """
    try:
        timeout = httpx.Timeout(5.0)
        async with httpx.AsyncClient(timeout=timeout) as session:
            response = await session.get(METRICS_URL)
            response.raise_for_status()
            return parse_prometheus_metrics(response.text)
    except Exception as e:
        logging.warning(f"Failed to fetch live metrics: {e}")
        # Fallback to registry-based metrics when Prometheus unavailable
        return fetch_registry_fallback()


def fetch_registry_fallback() -> Dict[str, Any]:
    """
    Fallback metrics fetching from strategy registry when live metrics unavailable.

    Returns simulated metrics based on stored registry data.
    """
    registry = load_json(REGISTRY_PATH, {})
    fallback = {"portfolio_equity_usd": 50000.0, "models": {}}  # Reasonable fallback

    for model_name, model_data in registry.items():
        if isinstance(model_data, dict):
            fallback["models"][model_name] = {
                "sharpe": model_data.get("sharpe", 0.0),
                "realized_pnl": model_data.get("realized", 0.0),
            }

    logging.info(f"Using registry fallback metrics: {len(fallback['models'])} models")
    return fallback


def calculate_target_allocation(
    policy: Dict[str, Any], equity: float, models: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate target capital quotas for each model based on current performance and policy.

    Returns dict of model -> target_quota mapping with decision metadata.
    """
    target_allocations = {}
    enabled_models = policy.get("enabled", [])

    if not enabled_models:
        return target_allocations

    # Calculate total available capital pool
    equity_fraction = policy.get("base_equity_frac", 0.2)
    total_pool = float(
        max(1000.0, equity * equity_fraction)
    )  # Minimum $1K even with no equity

    # Start with even split baseline
    base_allocation = total_pool / len(enabled_models)

    # Load current allocations to apply incremental adjustments
    current_allocations = load_json(ALLOCATIONS_PATH, {}).get("capital_quota_usd", {})
    last_updates = load_json(ALLOCATIONS_PATH, {}).get("updated_at", {})

    now = time.time()
    cooldown_sec = policy.get("cooldown_sec", 900)

    sharpe_promote = policy.get("sharpe_promote", 1.0)
    sharpe_demote = policy.get("sharpe_demote", 0.3)
    step_up_pct = policy.get("step_up_pct", 0.15)
    step_down_pct = policy.get("step_down_pct", 0.2)

    total_allocated = 0.0

    for model in enabled_models:
        current_quota = float(current_allocations.get(model, base_allocation))
        last_update = last_updates.get(model, 0)

        # Check cooldown period
        can_adjust = (now - last_update) >= cooldown_sec

        model_data = models.get(model, {})
        sharpe = model_data.get("sharpe", 0.0)
        realized_pnl = model_data.get("realized_pnl", 0.0)

        target_quota = current_quota
        decision = "hold"
        reason = f"cooldown_active_until_{last_update + cooldown_sec}"

        if can_adjust:
            if sharpe >= sharpe_promote:
                # Promote: grow allocation
                target_quota = current_quota * (1.0 + step_up_pct)
                decision = "promote"
                reason = f"sharpe_{sharpe:.2f}_gte_promote_{sharpe_promote}"

                # Update last update timestamp
                last_updates[model] = now

            elif sharpe < sharpe_demote:
                # Demote: shrink allocation
                target_quota = current_quota * (1.0 - step_down_pct)
                decision = "demote"
                reason = f"sharpe_{sharpe:.2f}_lt_demote_{sharpe_demote}"

                # Update last update timestamp
                last_updates[model] = now

            else:
                # Hold: no change
                decision = "hold"
                reason = f"sharpe_{sharpe:.2f}_neutral_range_{sharpe_demote}_to_{sharpe_promote}"

        # Apply bounds
        min_quota = policy.get("min_quota_usd", 250.0)
        max_quota = policy.get("max_quota_usd", 25000.0)
        target_quota = float(max(min_quota, min(max_quota, target_quota)))

        target_allocations[model] = {
            "target_quota": target_quota,
            "current_quota": current_quota,
            "sharpe": sharpe,
            "realized_pnl": realized_pnl,
            "decision": decision,
            "reason": reason,
            "last_update": last_update,
            "next_update": last_update + cooldown_sec,
        }

        total_allocated += target_quota

        # Log significant decisions
        if decision in ["promote", "demote"] or target_quota != current_quota:
            logging.info(
                f"[ALLOC] {model}: {decision} "
                f"${current_quota:.0f} -> ${target_quota:.0f} "
                f"(Sharpe: {sharpe:.2f}, Reason: {reason})"
            )

    # Normalize if total exceeds pool (though bounds should prevent this)
    if total_allocated > total_pool:
        scale_factor = total_pool / total_allocated
        logging.warning(
            f"[ALLOC] Oversubscribed capital ${total_allocated:.0f} > pool ${total_pool:.0f}, scaling down"
        )
        for model in target_allocations:
            target_allocations[model]["target_quota"] *= scale_factor

    return target_allocations


async def allocation_loop():
    """
    Main allocation optimization loop.

    Runs continuously, fetching metrics and adjusting model capital quotas.
    """
    # Load policy
    policy = load_json(
        POLICY_PATH,
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
            "enabled": ["ma_crossover_v3", "hmm_v2_canary"],
            "allocation_mode": "dynamic",
        },
    )

    # Initial state
    allocations = load_json(
        ALLOCATIONS_PATH, {"capital_quota_usd": {}, "updated_at": {}}
    )
    refresh_interval = policy.get("refresh_sec", 30)

    logging.info("[ALLOC] Starting dynamic capital allocator")
    logging.info(f"[ALLOC] Refresh interval: {refresh_interval}s")
    logging.info(f"[ALLOC] Enabled models: {policy.get('enabled', [])}")
    logging.info(f"[ALLOC] Metrics source: {METRICS_URL}")

    while True:
        try:
            # Fetch live metrics
            metrics = await fetch_live_metrics()

            if not metrics.get("models"):
                logging.warning(
                    "[ALLOC] No model metrics available, skipping allocation"
                )
                await asyncio.sleep(refresh_interval)
                continue

            equity = metrics.get("portfolio_equity_usd", 0.0)

            # Calculate target allocations
            target_allocations = calculate_target_allocation(
                policy, equity, metrics["models"]
            )

            # Apply new allocations
            new_quota_usd = {}
            for model, alloc_data in target_allocations.items():
                new_quota_usd[model] = alloc_data["target_quota"]

            # Update allocations file
            allocations.update(
                {
                    "capital_quota_usd": new_quota_usd,
                    "updated_at": {
                        model: alloc["last_update"]
                        for model, alloc in target_allocations.items()
                    },
                    "equity_usd": equity,
                    "ts": time.time(),
                    "details": target_allocations,
                }
            )

            save_json(ALLOCATIONS_PATH, allocations)

            # Summary logging
            total_allocated = sum(new_quota_usd.values())
            num_models = len(new_quota_usd)
            avg_allocation = total_allocated / max(1, num_models)

            logging.info(
                f"[ALLOC] Updated allocations: {num_models} models, "
                f"total=${total_allocated:,.0f}, avg=${avg_allocation:.0f} "
                f"(equity=${equity:,.0f})"
            )

        except Exception as e:
            logging.error(f"[ALLOC] Loop error: {e}")
            logging.error("[ALLOC] Continuing despite error...")

        await asyncio.sleep(refresh_interval)


# Convenience functions for external access


def get_model_quota(model: str) -> float:
    """Get current capital quota for a specific model."""
    allocations = load_json(ALLOCATIONS_PATH, {})
    return float(allocations.get("capital_quota_usd", {}).get(model, 0.0))


def get_all_allocations() -> Dict[str, Any]:
    """Get complete current allocation state."""
    return load_json(
        ALLOCATIONS_PATH,
        {
            "capital_quota_usd": {},
            "updated_at": {},
            "equity_usd": 0.0,
            "ts": time.time(),
        },
    )


async def simulate_allocation_cycle(
    policy: Dict = None, metrics: Dict = None
) -> Dict[str, Any]:
    """
    Simulate a single allocation cycle for testing.

    Args:
        policy: Override policy (none for default loading)
        metrics: Override metrics (none for live fetch)

    Returns:
        Allocation result dict
    """
    if policy is None:
        policy = load_json(
            POLICY_PATH,
            {
                "refresh_sec": 30,
                "base_equity_frac": 0.2,
                "min_quota_usd": 250.0,
                "max_quota_usd": 25000.0,
                "step_up_pct": 0.15,
                "step_down_pct": 0.20,
                "sharpe_promote": 1.0,
                "sharpe_demote": 0.3,
                "cooldown_sec": 0,  # No cooldown for testing
                "enabled": ["ma_crossover_v3", "hmm_v2_canary"],
            },
        )

    if metrics is None:
        metrics = await fetch_live_metrics()

    equity = metrics.get("portfolio_equity_usd", 50000.0)
    target_allocations = calculate_target_allocation(policy, equity, metrics["models"])

    # Apply allocations
    new_quota_usd = {
        model: alloc["target_quota"] for model, alloc in target_allocations.items()
    }

    result = {
        "policy": policy,
        "input_metrics": metrics,
        "equity": equity,
        "target_allocations": target_allocations,
        "final_quotas": new_quota_usd,
        "total_allocated": sum(new_quota_usd.values()),
        "simulation_ts": time.time(),
    }

    return result


# Startup integration
def integrate_with_ops():
    """Integration point for OPS API startup."""
    import ops.ops_api  # Will add startup handler

    logging.info("[ALLOC] Capital allocator integrated with OPS")
    return True
