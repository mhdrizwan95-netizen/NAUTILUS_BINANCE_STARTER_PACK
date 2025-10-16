# ops/strategy_selector.py
import json, logging, time, asyncio, httpx, os
from pathlib import Path
from datetime import datetime, timezone

REGISTRY_PATH = Path("ops/strategy_registry.json")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

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
    models = [(k, v) for k, v in registry.items() if k != "current_model" and isinstance(v, dict)]

    if not models:
        return []

    ranked = []
    for name, stats in models:
        # Require minimum data quality
        if _as_count(stats.get("samples", 0)) < 10:
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
    best_model, best_score, best_stats = ranked[0]

    if len(ranked) >= 2:
        second_best_model, second_score, _ = ranked[1]
        improvement = best_score - second_score
        # Only promote if clear edge (prevent thrashing on noise)
        should_promote = best_model != current and (improvement > 0.1 or current not in [r[0] for r in ranked])
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
        registry["promotion_log"].append({
            "time": utc_now(),
            "from": current,
            "to": best_model,
            "reason": (
                f"Sharpe improved {_as_float(best_stats.get('sharpe', 0.0)):.2f} > "
                f"{_as_float(registry.get(current, {}).get('sharpe', 0.0)):.2f}"
            )
        })

        # Keep only last 50 promotions for log size management
        registry["promotion_log"] = registry["promotion_log"][-50:]

        registry["current_model"] = best_model
        save_registry(registry)

        logging.info(f"[Governance] Promoted {best_model} (v{best_stats['version']}) at {best_stats['last_promotion']}")
        # Broadcast promotion to engines
        asyncio.run(push_model_update(best_model))
    elif len(ranked) >= 1 and current is None:
        # No current model set, initialize
        registry["current_model"] = best_model
        save_registry(registry)
        logging.info(f"[Governance] Initialized with best model: {best_model}")
        asyncio.run(push_model_update(best_model))

async def push_model_update(model_tag: str):
    """Broadcast strategy change to all running engines."""
    endpoints = os.getenv("ENGINE_ENDPOINTS", "http://engine_binance:8003").split(",")

    async with httpx.AsyncClient() as client:
        for url in endpoints:
            try:
                await client.post(f"{url.rstrip('/')}/strategy/promote", json={"model_tag": model_tag}, timeout=4.0)
                logging.debug(f"[Governance] Updated {url} to {model_tag}")
            except Exception as e:
                logging.warning(f"[Governance] Failed to update {url}: {e}")

def get_leaderboard() -> list:
    """Return current strategy leaderboard for API consumption."""
    registry = load_registry()
    ranked = rank_strategies(registry)
    current = registry.get("current_model")

    leaderboard = []
    for i, (name, score, stats) in enumerate(ranked):
        leaderboard.append({
            "name": name,
            "rank": i + 1,
            "score": round(score, 3),
            "sharpe": round(_as_float(stats.get("sharpe", 0.0)), 3),
            "drawdown": round(_as_float(stats.get("drawdown", 0.0)), 3),
            "realized": round(_as_float(stats.get("realized", 0.0)), 2),
            "trades": _as_count(stats.get("trades", 0)),
            "samples": _as_count(stats.get("samples", 0)),
            "is_current": (name == current)
        })

    return leaderboard
