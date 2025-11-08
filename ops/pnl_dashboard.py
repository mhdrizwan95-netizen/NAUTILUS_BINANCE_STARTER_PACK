"""
PnL Attribution Dashboard - Model-Level Performance Transparency

Provides real-time and historical performance attribution across all models,
venues, and strategies. Enables fund-level transparency and strategy comparison.

Design Philosophy:
- Complete isolation by model/venue for fair attribution
- Real-time updates from Prometheus metrics
- Historical exports for trend analysis
- Executive-grade visualization and reporting
"""

import json
import os
import statistics
import time
from pathlib import Path

import httpx
from fastapi import APIRouter

router = APIRouter()

METRICS_URL = os.getenv("OPS_METRICS_URL", "http://localhost:8002/metrics")
REGISTRY_PATH = Path("ops/strategy_registry.json")
EXPORTS_DIR = Path("ops/exports")
EXPORTS_DIR.mkdir(exist_ok=True)


def parse_prometheus_metrics(metrics_text: str) -> list:
    """
    Parse Prometheus-formatted metrics text and aggregate by model/venue labels.

    Returns structured list of model-venue performance data.
    """
    model_venue_data = {}  # Key: "model:venue"

    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "{" in line and "}" in line:
            # Parse metric line like: orders_filled_total{venue="BINANCE",model="hmm_v3"} 42
            metric_part = line.split("{")[0].strip()
            labels_part = line.split("{")[1].split("}")[0]
            value_part = line.split("}")[-1].strip()

            try:
                value = float(value_part)
                labels = parse_labels(labels_part)
                model = labels.get("model", "unknown")
                venue = labels.get("venue", "global")

                key = f"{model}:{venue}"

                if key not in model_venue_data:
                    model_venue_data[key] = {
                        "model": model,
                        "venue": venue,
                        "orders_filled_total": 0,
                        "orders_submitted_total": 0,
                        "pnl_realized_total": 0.0,
                        "pnl_unrealized_total": 0.0,
                        "trades": 0,
                    }

                # Map metrics to our data structure
                data = model_venue_data[key]
                if metric_part == "orders_filled_total":
                    data["orders_filled_total"] = value
                elif metric_part == "orders_submitted_total":
                    data["orders_submitted_total"] = value
                elif metric_part == "pnl_realized_total":
                    data["pnl_realized_total"] = value
                elif metric_part == "pnl_unrealized_total":
                    data["pnl_unrealized_total"] = value
                elif metric_part == "trades_total":
                    data["trades"] = value

            except (ValueError, IndexError):
                continue

    # Convert to list and calculate derived metrics
    result = list(model_venue_data.values())
    for item in result:
        # Calculate win rate
        submitted = item.get("orders_submitted_total", 0)
        filled = item.get("orders_filled_total", 0)
        item["win_rate"] = (filled / submitted) if submitted > 0 else 0.0

        # Calculate total PnL
        realized = item.get("pnl_realized_total", 0.0)
        unrealized = item.get("pnl_unrealized_total", 0.0)
        item["total_pnl"] = realized + unrealized

        # Calculate return percentage (simplified - against initial capital)
        # In production, you'd track this more carefully
        item["return_pct"] = ((realized / 1000.0) * 100) if realized != 0 else 0.0

    return result


def parse_labels(labels_str: str) -> dict:
    """Parse Prometheus label string like 'venue="BINANCE",model="hmm_v3"'."""
    labels = {}
    for kv in labels_str.split(","):
        kv = kv.strip()
        if "=" in kv:
            key, value = kv.split("=", 1)
            labels[key.strip()] = value.strip('"')
    return labels


def load_registry_data() -> dict:
    """Load strategy registry data for Sharpe, drawdown, etc."""
    if not REGISTRY_PATH.exists():
        return {}

    try:
        return json.loads(REGISTRY_PATH.read_text())
    except Exception:
        return {}


def enhance_with_registry_data(performance_data: list) -> list:
    """Merge registry statistics (Sharpe, drawdown) with live metrics."""
    registry = load_registry_data()

    for item in performance_data:
        model = item["model"]
        if model in registry:
            reg_data = registry[model]

            # Add registry-calculated metrics
            item["sharpe"] = reg_data.get("sharpe", 0.0)
            item["drawdown"] = reg_data.get("drawdown", 0.0)
            item["max_drawdown"] = reg_data.get("max_drawdown", 0.0)
            item["avg_win"] = reg_data.get("avg_win", 0.0)
            item["avg_loss"] = reg_data.get("avg_loss", 0.0)
            item["win_rate"] = reg_data.get("win_rate", item.get("win_rate", 0.0))
            item["trading_days"] = reg_data.get("trading_days", 0)

            # Add metadata
            item["strategy_type"] = reg_data.get("strategy_type", "unknown")
            item["version"] = reg_data.get("version", "1.0")
            item["created_at"] = reg_data.get("created_at", "unknown")

    return performance_data


@router.get("/dash/pnl")
async def pnl_dashboard():
    """
    Comprehensive PnL attribution dashboard.

    Returns real-time performance by model and venue with all key metrics.
    """
    try:
        # Fetch live metrics from Prometheus
        timeout = httpx.Timeout(5.0)
        async with httpx.AsyncClient(timeout=timeout) as session:
            response = await session.get(METRICS_URL)
            response.raise_for_status()
            metrics_text = response.text

        # Parse and aggregate metrics
        performance_data = parse_prometheus_metrics(metrics_text)

        # Enhance with registry data (Sharpe, drawdown, etc.)
        enhanced_data = enhance_with_registry_data(performance_data)

        # Calculate summary statistics
        total_realized_pnl = sum(item["pnl_realized_total"] for item in enhanced_data)
        total_unrealized_pnl = sum(item["pnl_unrealized_total"] for item in enhanced_data)
        total_trades = sum(item["orders_filled_total"] for item in enhanced_data)

        # Calculate portfolio-level metrics
        portfolio_metrics = {
            "total_realized_pnl": total_realized_pnl,
            "total_unrealized_pnl": total_unrealized_pnl,
            "total_pnl": total_realized_pnl + total_unrealized_pnl,
            "total_trades": total_trades,
            "win_rate_overall": calculate_overall_win_rate(enhanced_data),
            "sharpe_portfolio": calculate_portfolio_sharpe(enhanced_data),
            "max_drawdown_portfolio": max(
                (item.get("max_drawdown", 0) for item in enhanced_data), default=0.0
            ),
        }

        return {
            "timestamp": time.time(),
            "portfolio_summary": portfolio_metrics,
            "models": enhanced_data,
            "meta": {
                "metrics_source": METRICS_URL,
                "registry_source": str(REGISTRY_PATH),
                "models_count": len(enhanced_data),
                "venues_count": len(set(item["venue"] for item in enhanced_data)),
            },
        }

    except Exception as e:
        return {
            "error": f"Dashboard generation failed: {str(e)}",
            "timestamp": time.time(),
        }


@router.get("/dash/pnl/model/{model_name}")
async def model_performance(model_name: str):
    """Detailed performance for a specific model across all venues."""
    data = await pnl_dashboard()

    if "models" not in data:
        return {"error": "No performance data available"}

    model_data = [item for item in data["models"] if item["model"] == model_name]

    if not model_data:
        return {"error": f"No data found for model: {model_name}"}

    # Aggregate across venues for this model
    total_realized = sum(floor_data["pnl_realized_total"] for floor_data in model_data)
    total_unrealized = sum(floor_data["pnl_unrealized_total"] for floor_data in model_data)
    total_trades = sum(floor_data["orders_filled_total"] for floor_data in model_data)

    # Use registry data for strategy-level metrics
    registry = load_registry_data()
    strategy_info = registry.get(model_name, {})

    return {
        "model": model_name,
        "venues": model_data,
        "aggregated": {
            "total_realized_pnl": total_realized,
            "total_unrealized_pnl": total_unrealized,
            "total_pnl": total_realized + total_unrealized,
            "total_trades": total_trades,
            "win_rate": sum(d["win_rate"] * d["orders_submitted_total"] for d in model_data)
            / max(1, sum(d["orders_submitted_total"] for d in model_data)),
            "sharpe": strategy_info.get("sharpe", 0.0),
            "max_drawdown": max((d.get("max_drawdown", 0) for d in model_data), default=0.0),
        },
        "strategy_info": strategy_info,
        "timestamp": time.time(),
    }


def calculate_overall_win_rate(model_data: list) -> float:
    """Calculate portfolio-level win rate."""
    total_submitted = sum(item.get("orders_submitted_total", 0) for item in model_data)
    total_filled = sum(item.get("orders_filled_total", 0) for item in model_data)

    return (total_filled / total_submitted) if total_submitted > 0 else 0.0


def calculate_portfolio_sharpe(model_data: list) -> float:
    """Simple portfolio Sharpe calculation (simplified)."""
    returns = [item.get("return_pct", 0) for item in model_data if item.get("return_pct", 0) != 0]

    if len(returns) < 2:
        return 0.0

    avg_return = statistics.mean(returns)
    std_return = statistics.pstdev(returns)  # Population standard deviation

    # Assume 0% risk-free rate for simplicity
    return (avg_return / std_return) if std_return > 0 else 0.0
