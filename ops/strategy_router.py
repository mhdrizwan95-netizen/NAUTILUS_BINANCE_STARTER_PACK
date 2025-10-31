"""
Strategy Router - Pandora's Box of Model Traffic Distribution

Distributes trading signals across multiple models using weighted probabilistic routing.
Controls the canary deployment pipeline, ensuring safe and measured rollout of new strategies.

Architecture:
- Weighted random selection for traffic distribution
- Capital quota enforcement and automatic scaling
- Price discovery for quantity-to-quote conversions
- Real-time configuration updates
- Comprehensive audit logging
- Integration with OPS governance and telemetry
"""
import asyncio
import json
import logging
import os
import random
import time
import math
from pathlib import Path
from typing import Dict, List, Any, Optional

import httpx

from ops.strategy_selector import promote_best
from ops.capital_allocator import get_model_quota


# Configuration
WEIGHTS_PATH = Path("ops/strategy_weights.json")
ENGINE_ENDPOINTS = [e.strip() for e in os.getenv("ENGINE_ENDPOINTS", "http://engine_binance:8003").split(",")
                   if e.strip()]

# Prometheus-style metrics (would replace with actual prometheus client)
class StrategyMetrics:
    """Simple in-memory metrics for strategy routing."""
    def __init__(self):
        self.signal_routed = {}  # model -> count
        self.signal_failed = {}  # model -> count
        self.routing_decisions = []  # Last 1000 decisions

    def increment_signal_routed(self, model: str):
        self.signal_routed[model] = self.signal_routed.get(model, 0) + 1

    def increment_signal_failed(self, model: str):
        self.signal_failed[model] = self.signal_failed.get(model, 0) + 1

    def log_decision(self, signal_id: str, model: str, weight: float):
        self.routing_decisions.append({
            "timestamp": time.time(),
            "signal_id": signal_id,
            "model": model,
            "weight": weight,
            "decision_type": "weighted_routing"
        })
        if len(self.routing_decisions) > 1000:
            self.routing_decisions = self.routing_decisions[-1000:]

# Global metrics
metrics = StrategyMetrics()


def _load_weights() -> Dict[str, Any]:
    """Load strategy weights configuration."""
    if not WEIGHTS_PATH.exists():
        # Return default configuration
        return {
            "current": "hmm_v3_ensemble",
            "weights": {"hmm_v3_ensemble": 1.0},
            "min_trades_for_eval": 50,
            "min_live_hours": 6,
            "max_canary_weight": 0.15,
            "auto_promotion_enabled": True,
            "manual_override_allowed": True
        }

    try:
        return json.loads(WEIGHTS_PATH.read_text())
    except Exception as e:
        logging.error(f"[ROUTER] Failed to load weights: {e}")
        return {"current": "fallback", "weights": {"fallback": 1.0}}


def choose_model(signal_id: Optional[str] = None) -> str:
    """
    Select a model using weighted probabilistic routing.

    Args:
        signal_id: Optional identifier for signal tracing

    Returns:
        Selected model tag
    """
    if not signal_id:
        signal_id = f"sig_{int(time.time() * 1000000)}"

    config = _load_weights()
    weights = config.get("weights", {})
    max_canary = config.get("max_canary_weight", 0.15)

    # Validate weights
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 0.001:
        logging.warning(f"[ROUTER] Weights don't sum to 1.0: {total_weight}")
        # Normalize
        weights = {k: v/total_weight for k, v in weights.items()}

    # Ensure no canary exceeds max weight
    current = config.get("current", "")
    for model, weight in list(weights.items()):
        if model != current and weight > max_canary:
            logging.warning(f"[ROUTER] Reducing {model} weight from {weight} to {max_canary}")
            weights[model] = max_canary
            # Redistribute to current model
            excess = weight - max_canary
            weights[current] = weights.get(current, 0) + excess

    # Perform weighted selection
    r = random.random()
    cumulative = 0.0

    for model, weight in weights.items():
        cumulative += weight
        if r <= cumulative:
            # Log decision
            metrics.log_decision(signal_id, model, weight)

            # Is this a canary model?
            if model != current and weight > 0:
                logging.info(f"[ROUTER] 🐤 Canary deployment: Using {model} ({weight*100:.1f}%)")

            return model

    # Fallback to first model
    first_model = list(weights.keys())[0]
    logging.error(f"[ROUTER] Weighted selection failed, using {first_model}")
    return first_model


async def route_signal(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Route a trading signal to an appropriate model based on current weights.

    Args:
        signal_data: Signal payload (symbol, side, quote, etc.)

    Returns:
        Response with model assignment and execution result
    """
    start_time = time.time()

    # Choose model
    model = choose_model(signal_data.get("id", f"sig_{int(time.time() * 1000000)}"))

    # Add model tag to signal
    signal_data["model_tag"] = model

    # Attempt delivery to engine
    success = False
    result = {"error": "No engines configured"}

    for endpoint in ENGINE_ENDPOINTS:
        try:
            timeout = httpx.Timeout(10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{endpoint}/strategy/signal",
                    json=signal_data,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 404:
                    # fallback to legacy orders endpoint for older engines
                    response = await client.post(
                        f"{endpoint}/orders/market",
                        json=signal_data,
                        headers={"Content-Type": "application/json"},
                    )

                response.raise_for_status()
                result = response.json()
                result["model_tag"] = model
                result["routing_time"] = time.time() - start_time

                metrics.increment_signal_routed(model)
                success = True

                logging.info(f"[ROUTER] ✅ Signal routed to {model} in {result['routing_time']:.2f}s")
                break

        except Exception as e:
            logging.warning(f"[ROUTER] Engine {endpoint} failed for {model}: {e}")
            continue

    if not success:
        metrics.increment_signal_failed(model)
        result = {
            "error": f"All engines failed for model {model}",
            "model_tag": model,
            "status": "routing_failed"
        }
        logging.error(f"[ROUTER] ❌ Signal routing failed for {model}")

    return result


async def route_signal_with_allocation(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Route a trading signal with capital allocation and quota enforcement.

    Args:
        signal_data: Signal payload (symbol, side, quote, etc.)

    Returns:
        Response with model assignment, quota info, and execution result
    """
    start_time = time.time()

    # Choose model using weighted routing
    model = choose_model(signal_data.get("id", f"sig_{int(time.time() * 1000000)}"))
    signal_data["model_tag"] = model

    # Get capital quota for this model
    quota_usd = get_model_quota(model)

    # Apply capital scaling based on quota
    original_quote = signal_data.get("quote")
    original_quantity = signal_data.get("quantity")

    if original_quote is not None and quota_usd > 0:
        # Clip quote to available quota
        adjusted_quote = min(float(original_quote), quota_usd)
        signal_data["quote"] = adjusted_quote
        logging.info(f"[ROUTER] 💰 Capital allocation: {model} quota ${quota_usd:.0f}, "
                    f"requested ${original_quote:.0f}, adjusted to ${adjusted_quote:.0f}")

    elif original_quantity is not None and quota_usd > 0:
        # Convert quantity to quote, then clip to quota, then convert back
        price = await fetch_price_for_symbol(signal_data.get("symbol", ""))
        if price > 0:
            quote_equivalent = float(original_quantity) * price
            adjusted_quote = min(quote_equivalent, quota_usd)
            adjusted_quantity = adjusted_quote / price
            signal_data["quantity"] = adjusted_quantity
            logging.info(f"[ROUTER] 💰 Capital allocation: {model} quota ${quota_usd:.0f}, "
                        f"requested qty {original_quantity:.6f} (${quote_equivalent:.0f}), "
                        f"adjusted to qty {adjusted_quantity:.6f} (${adjusted_quote:.0f})")

    # Attempt delivery to engine
    success = False
    result = {"error": "No engines configured"}

    for endpoint in ENGINE_ENDPOINTS:
        try:
            timeout = httpx.Timeout(10.0)  # 10 second timeout
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{endpoint}/strategy/signal",
                    json=signal_data,
                    headers={"Content-Type": "application/json"}
                )

                response.raise_for_status()
                result = response.json()
                result["model_tag"] = model
                result["capital_quota_usd"] = quota_usd
                result["original_quote"] = original_quote
                result["original_quantity"] = original_quantity
                result["allocation_adjusted"] = (
                    signal_data.get("quote", original_quote) != original_quote or
                    signal_data.get("quantity", original_quantity) != original_quantity
                )
                result["routing_time"] = time.time() - start_time

                metrics.increment_signal_routed(model)
                success = True

                logging.info(f"[ROUTER] ✅ Signal routed to {model} with allocation in {result['routing_time']:.2f}s")

                break  # Success, exit engine loop

        except Exception as e:
            logging.warning(f"[ROUTER] Engine {endpoint} failed for {model}: {e}")
            continue

    if not success:
        metrics.increment_signal_failed(model)
        result = {
            "error": f"All engines failed for model {model}",
            "model_tag": model,
            "capital_quota_usd": quota_usd,
            "status": "routing_failed"
        }
        logging.error(f"[ROUTER] ❌ Signal routing failed for {model}")

    return result


async def fetch_price_for_symbol(symbol: str) -> float:
    """
    Fetch current price for a symbol from engine.

    Args:
        symbol: Trading symbol (e.g., "BTCUSDT.BINANCE")

    Returns:
        Price as float, or 0.0 if unavailable
    """
    if not symbol:
        return 0.0

    # Try to get price from first available engine
    for endpoint in ENGINE_ENDPOINTS:
        try:
            timeout = httpx.Timeout(3.0)
            async with httpx.AsyncClient(timeout=timeout) as session:
                # Assume engine has a price endpoint
                response = await session.get(f"{endpoint}/price", params={"symbol": symbol})
                if response.status_code == 200:
                    data = response.json()
                    return float(data.get("price", 0.0))
        except Exception:
            continue

    logging.warning(f"[ROUTER] Price fetch failed for {symbol}")
    return 0.0


# FastAPI Router
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.post("/strategy/signal")
async def strategy_signal_endpoint(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """Primary endpoint for routing trading signals to models."""
    try:
        if not signal_data:
            raise HTTPException(status_code=400, detail="Empty signal data")

        # Validate required fields
        required = ["symbol", "side"]
        optional = ["quote", "quantity"]

        if not any(signal_data.get(field) for field in required + optional):
            raise HTTPException(status_code=400, detail="Missing required signal fields")

        # Route and execute signal with capital allocation
        result = await route_signal_with_allocation(signal_data)
        result["timestamp"] = time.time()

        return result

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[ROUTER] Signal routing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Routing failed: {str(e)}")


@router.get("/strategy/weights")
def get_weights_endpoint():
    """Get current strategy weights configuration."""
    try:
        return _load_weights()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load weights: {e}")


@router.post("/strategy/weights")
async def set_weights_endpoint(body: Dict[str, Any]):
    """Update strategy weights (admin operation)."""
    try:
        config = _load_weights()

        # Validate manual override permission
        if not config.get("manual_override_allowed", False):
            raise HTTPException(status_code=403, detail="Manual overrides disabled")

        # Update weights
        new_weights = body.get("weights", {})
        total = sum(new_weights.values())

        if abs(total - 1.0) > 0.001:
            raise HTTPException(status_code=400, detail=f"Weights must sum to 1.0, got {total}")

        # Validate no canary exceeds max
        max_canary = config.get("max_canary_weight", 0.15)
        current = config.get("current", "")
        for model, weight in new_weights.items():
            if model != current and weight > max_canary:
                raise HTTPException(
                    status_code=400,
                    detail=f"Canary weight {weight} exceeds max {max_canary} for {model}"
                )

        # Apply updates
        config["weights"] = new_weights
        config["last_updated"] = int(time.time())

        WEIGHTS_PATH.write_text(json.dumps(config, indent=2))

        logging.info(f"[ROUTER] 🔄 Weights updated: {new_weights}")

        # Notify governance system
        try:
            from ops import governance_daemon
            # Trigger governance event
            asyncio.create_task(governance_daemon.BUS.publish(
                "strategy.weights_updated",
                {"new_weights": new_weights, "updated_by": "admin"}
            ))
        except ImportError:
            pass

        return {"status": "success", "weights": new_weights}

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[ROUTER] Weight update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")


@router.post("/strategy/promote_canary")
async def promote_canary_endpoint(body: Dict[str, Any]):
    """Manually promote a canary model (forced operation)."""
    try:
        candidate = body.get("model")
        if not candidate:
            raise HTTPException(status_code=400, detail="model required")

        config = _load_weights()

        if not config.get("manual_override_allowed", False):
            raise HTTPException(status_code=403, detail="Manual promotes disabled")

        # Perform promotion
        old_current = config["current"]
        config["current"] = candidate
        config["weights"] = {candidate: 1.0}  # Graduate to full production
        config["last_updated"] = int(time.time())

        WEIGHTS_PATH.write_text(json.dumps(config, indent=2))

        logging.info(f"[ROUTER] 🚀 Manual promotion: {old_current} → {candidate}")

        # Notify systems
        try:
            from ops import governance_daemon
            asyncio.create_task(governance_daemon.BUS.publish(
                "strategy.manual_promotion",
                {"old_model": old_current, "new_model": candidate, "promoted_by": "admin"}
            ))
        except ImportError:
            pass

        return {
            "status": "promoted",
            "old_current": old_current,
            "new_current": candidate
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[ROUTER] Promotion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Promotion failed: {e}")


@router.get("/strategy/metrics")
def get_routing_metrics():
    """Get strategy routing performance metrics."""
    config = _load_weights()

    total_routed = sum(metrics.signal_routed.values())
    total_failed = sum(metrics.signal_failed.values())

    model_stats = {}
    for model in config.get("weights", {}).keys():
        model_stats[model] = {
            "routed": metrics.signal_routed.get(model, 0),
            "failed": metrics.signal_failed.get(model, 0),
            "weight": config["weights"].get(model, 0)
        }

    return {
        "total_signals": total_routed + total_failed,
        "total_routed": total_routed,
        "total_failed": total_failed,
        "success_rate": total_routed / max(total_routed + total_failed, 1),
        "model_stats": model_stats,
        "recent_decisions": metrics.routing_decisions[-10:]  # Last 10
    }


# Register with OPS API
def setup_strategy_router(app):
    """Register strategy router with FastAPI app."""
    from ops.ops_api import app as ops_app
    ops_app.include_router(router, prefix="", tags=["strategy"])

    logging.info("[ROUTER] Strategy router initialized with probabilistic routing")
