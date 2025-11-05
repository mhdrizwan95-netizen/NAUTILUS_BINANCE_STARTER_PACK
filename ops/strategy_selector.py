# ops/strategy_selector.py
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from ops.env import engine_endpoints
from ops.net import create_async_client, request_with_retry

REGISTRY_PATH = Path("ops/strategy_registry.json")
WEIGHTS_PATH = Path("ops/strategy_weights.json")
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)


def utc_now():
    return datetime.now(tz=timezone.utc).isoformat()


def load_registry():
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except Exception:
        return {"current_model": None, "promotion_log": []}


def save_registry(d: dict):
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(REGISTRY_PATH)


def _as_float(x, default: float = 0.0) -> float:
    try:
        if isinstance(x, list):
            # common pattern: store history list; use last value
            return float(x[-1]) if x else float(default)
        if isinstance(x, (int, float)):
            return float(x)
        return float(x)
    except Exception:
        return float(default)


def _as_count(x, default: int = 0) -> int:
    try:
        if isinstance(x, list):
            return int(len(x))
        if isinstance(x, (int, float)):
            return int(x)
        return int(x)
    except Exception:
        return int(default)


def rank_strategies(registry: dict) -> list:
    """
    Rank strategies by composite score: Sharpe ratio primary, drawdown penalty
    Returns list of (model_name, score, stats) tuples, desc sorted.
    """
    models = [
        (k, v)
        for k, v in registry.items()
        if k != "current_model" and isinstance(v, dict)
    ]

    if not models:
        return []

    ranked = []
    for name, stats in models:
        if bool(stats.get("manual")):
            continue
        sample_count = _as_count(stats.get("samples", 0))
        trade_count = _as_count(stats.get("trades", 0))
        if sample_count < 3 and trade_count < 50:
            continue

        sharpe = _as_float(stats.get("sharpe", 0.0))
        drawdown = _as_float(stats.get("drawdown", 0.0))
        realized = _as_float(stats.get("realized", 0.0))

        # Composite score: boost Sharpe, penalize drawdown
        score = sharpe - (drawdown * 0.1) + (realized * 0.001)
        ranked.append((name, score, stats))

    # Sort by score descending (higher is better)
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def promote_best():
    """Evaluate current performance and promote the best strategy if it's a significant improvement."""
    registry = load_registry()
    ranked = rank_strategies(registry)

    if not ranked:
        logging.debug("[Governance] No qualified models to evaluate")
        return

    current = registry.get("current_model")
    if current:
        current_stats = registry.get(current) or {}
        if current_stats.get("manual"):
            logging.info(
                "[Governance] Manual override active for %s; skipping auto promotion",
                current,
            )
            return
    best_model, best_score, best_stats = ranked[0]

    if len(ranked) >= 2:
        second_best_model, second_score, _ = ranked[1]
        improvement = best_score - second_score
        threshold = 0.05
        should_promote = best_model != current and (
            improvement > threshold or current not in [r[0] for r in ranked]
        )
    else:
        should_promote = best_model != current

    if should_promote:
        # version bump for promotion
        best_stats["version"] = best_stats.get("version", 0) + 1
        best_stats["last_promotion"] = utc_now()

        # Initialize promotion log if it doesn't exist
        if "promotion_log" not in registry:
            registry["promotion_log"] = []

        # Add to promotion log
        registry["promotion_log"].append(
            {
                "time": utc_now(),
                "from": current,
                "to": best_model,
                "reason": (
                    f"Sharpe improved {_as_float(best_stats.get('sharpe', 0.0)):.2f} > "
                    f"{_as_float(registry.get(current, {}).get('sharpe', 0.0)):.2f}"
                ),
            }
        )

        # Keep only last 50 promotions for log size management
        registry["promotion_log"] = registry["promotion_log"][-50:]

        registry["current_model"] = best_model
        save_registry(registry)

        logging.info(
            f"[Governance] Promoted {best_model} (v{best_stats['version']}) at {best_stats['last_promotion']}"
        )
        _sync_router_weights(best_model)
        # Broadcast promotion to engines
        asyncio.run(push_model_update(best_model))
    elif len(ranked) >= 1 and current is None:
        # No current model set, initialize
        registry["current_model"] = best_model
        save_registry(registry)
        logging.info(f"[Governance] Initialized with best model: {best_model}")
        _sync_router_weights(best_model)
        asyncio.run(push_model_update(best_model))


def _sync_router_weights(current_model: str) -> None:
    """Ensure the strategy router weights mirror the promoted model."""
    try:
        if WEIGHTS_PATH.exists():
            config = json.loads(WEIGHTS_PATH.read_text())
        else:
            config = {}
    except Exception as exc:  # noqa: BLE001
        logging.error("[Governance] Failed to read strategy_weights.json: %s", exc)
        config = {}

    weights = config.get("weights") or {}
    # Ensure promoted model is present and dominates routing
    weights = {model: (1.0 if model == current_model else 0.0) for model in weights}
    if current_model not in weights:
        weights[current_model] = 1.0

    config.update({"current": current_model, "weights": weights})

    try:
        WEIGHTS_PATH.write_text(json.dumps(config, indent=2))
        logging.info("[Governance] Router weights updated for %s", current_model)
    except Exception as exc:  # noqa: BLE001
        logging.error("[Governance] Failed to update strategy_weights.json: %s", exc)


async def push_model_update(model_tag: str):
    """Broadcast strategy change to all running engines."""
    endpoints = engine_endpoints()

    async with create_async_client() as client:
        for url in endpoints:
            endpoint = f"{url.rstrip('/')}/strategy/promote"
            try:
                response = await request_with_retry(
                    client,
                    "POST",
                    endpoint,
                    json={"model_tag": model_tag},
                    retries=3,
                    backoff_base=0.5,
                )
                response.raise_for_status()
                logging.debug("[Governance] Updated %s to %s", endpoint, model_tag)
            except Exception as exc:  # noqa: BLE001
                logging.error(
                    "[Governance] failed to update %s after retries: %s",
                    endpoint,
                    exc,
                )


def get_leaderboard() -> list:
    """Return current strategy leaderboard for API consumption."""
    registry = load_registry()
    ranked = rank_strategies(registry)
    current = registry.get("current_model")

    leaderboard = []
    for i, (name, score, stats) in enumerate(ranked):
        leaderboard.append(
            {
                "name": name,
                "rank": i + 1,
                "score": round(score, 3),
                "sharpe": round(_as_float(stats.get("sharpe", 0.0)), 3),
                "drawdown": round(_as_float(stats.get("drawdown", 0.0)), 3),
                "realized": round(_as_float(stats.get("realized", 0.0)), 2),
                "trades": _as_count(stats.get("trades", 0)),
                "samples": _as_count(stats.get("samples", 0)),
                "is_current": (name == current),
            }
        )

    return leaderboard
