"""
Canary Manager - The Scientific Method Applied to Model Deployment

Orchestrates the complete canary deployment lifecycle:
- Risk-free testing with minimal exposure
- Statistical evaluation of live performance
- Automatic promotion of winners, rollback of losers
- Continuous optimization without human intervention

This bridges the gap between "hope it works" and "science proves it works".
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Tuple

import httpx

from ops.strategy_router import _load_weights, WEIGHTS_PATH


class CanaryEvaluator:
    """Evaluates canary model performance using statistical methods."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.min_trades = config.get("min_trades_for_eval", 50)
        self.min_hours = config.get("min_live_hours", 6)
        self.promotion_threshold_pct = config.get("promotion_threshold_pct", 5.0)
        self.rollback_threshold_pct = config.get("rollback_threshold_pct", -20.0)
        self.metrics_url = os.getenv("OPS_METRICS_URL", "http://localhost:8002/metrics")

    async def _fetch_model_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Fetch model-labeled metrics from OPS/Prometheus."""
        try:
            timeout = httpx.Timeout(5.0)
            async with httpx.AsyncClient(timeout=timeout) as session:
                response = await session.get(self.metrics_url)
                response.raise_for_status()
                return self._parse_metrics(response.text)
        except Exception as e:
            logging.error(f"[CANARY] Failed to fetch metrics: {e}")
            return {}

    def _parse_metrics(self, metrics_text: str) -> Dict[str, Dict[str, Any]]:
        """Parse Prometheus-style metrics into model-focused data."""
        model_data = {}

        for line in metrics_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse metric lines
            if "{" in line and "}" in line:
                # orders_filled_total{venue="BINANCE",model="hmm_v3"} 42
                # pnl_realized_total{model="hmm_v3"} 123.45
                metric_name = line.split("{")[0]
                labels_part = line.split("{")[1].split("}")[0]
                value_part = line.split("}")[-1].strip()

                try:
                    value = float(value_part)
                    labels = self._parse_labels(labels_part)
                    model = labels.get("model", "unknown")

                    if model not in model_data:
                        model_data[model] = {
                            "orders_filled": 0,
                            "orders_submitted": 0,
                            "orders_rejected": 0,
                            "pnl_realized": 0.0,
                            "pnl_unrealized": 0.0,
                        }

                    # Map metric names to our data structure
                    if metric_name == "orders_filled_total":
                        model_data[model]["orders_filled"] += int(value)
                    elif metric_name == "orders_submitted_total":
                        model_data[model]["orders_submitted"] += int(value)
                    elif metric_name == "orders_rejected_total":
                        model_data[model]["orders_rejected"] += int(value)
                    elif metric_name == "pnl_realized_total":
                        model_data[model]["pnl_realized"] += value
                    elif metric_name == "pnl_unrealized_total":
                        model_data[model]["pnl_unrealized"] += value

                except (ValueError, IndexError):
                    continue

        return model_data

    def _parse_labels(self, labels_str: str) -> Dict[str, str]:
        """Parse Prometheus label string like 'venue="BINANCE",model="hmm_v3"'."""
        labels = {}
        for kv in labels_str.split(","):
            kv = kv.strip()
            if "=" in kv:
                key, value = kv.split("=", 1)
                labels[key.strip()] = value.strip('"')
        return labels

    def _calculate_win_rate(self, metrics: Dict[str, Any]) -> float:
        """Calculate win rate as filled orders / submitted orders."""
        submitted = metrics["orders_submitted"]
        if submitted == 0:
            return 0.0
        filled = metrics["orders_filled"]
        return filled / submitted

    def _calculate_performance_score(
        self, model_metrics: Dict[str, Any], baseline_metrics: Dict[str, Any]
    ) -> Tuple[float, str]:
        """
        Calculate comparative performance score.

        Returns:
            Tuple of (relative_performance_pct, rating)
        """
        model_pnl = model_metrics["pnl_realized"]
        baseline_pnl = baseline_metrics["pnl_realized"]

        if baseline_pnl == 0:
            return (0.0, "insufficient_baseline")  # Can't evaluate without baseline

        relative_pct = ((model_pnl - baseline_pnl) / abs(baseline_pnl)) * 100

        # Statistical significance check (simplified)
        model_trades = model_metrics["orders_filled"]
        baseline_trades = baseline_metrics["orders_filled"]

        # Require minimum trade counts for statistical relevance
        if model_trades < self.min_trades or baseline_trades < self.min_trades:
            rating = "insufficient_data"
        elif relative_pct >= self.promotion_threshold_pct:
            rating = "promotion_candidate"
        elif relative_pct <= self.rollback_threshold_pct:
            rating = "rollback_candidate"
        else:
            rating = "neutral"

        return relative_pct, rating


class CanaryManager:
    """
    Orchestrates the complete canary deployment pipeline.

    Handles:
    - Model lifecycle from canary to production
    - Statistical evaluation against baselines
    - Automatic promotion and rollback decisions
    - Multi-stage deployment progression
    """

    def __init__(self):
        self.evaluator = CanaryEvaluator(_load_weights())
        self.audit_log = []  # Can be persisted to disk

    async def evaluate_canaries(self) -> Dict[str, Any]:
        """
        Evaluate all active canary deployments.

        Returns detailed performance assessment and recommendations.
        """
        evaluation_start = time.time()
        results = {
            "evaluation_timestamp": evaluation_start,
            "canaries_evaluated": [],
            "promotions": [],
            "rollbacks": [],
            "holdings": [],
        }

        try:
            # Load current configuration
            config = _load_weights()
            current_model = config.get("current", "")
            weights = config.get("weights", {})

            # Fetch live metrics
            model_metrics = await self.evaluator._fetch_model_metrics()

            if not model_metrics:
                results["error"] = "No metrics available for evaluation"
                return results

            # Evaluate each canary
            for model_name, weight in weights.items():
                if model_name == current_model:
                    continue  # Skip production model

                if weight <= 0:
                    continue  # Inactive canary

                canary_result = await self._evaluate_single_canary(
                    model_name, weight, model_metrics, current_model, config
                )

                results["canaries_evaluated"].append(canary_result)

                # Process recommendations
                if canary_result["recommendation"] == "promote":
                    await self._promote_canary(model_name, canary_result, config)
                    results["promotions"].append(model_name)
                elif canary_result["recommendation"] == "rollback":
                    await self._rollback_canary(model_name, canary_result, config)
                    results["rollbacks"].append(model_name)
                else:
                    results["holdings"].append(model_name)

            results["evaluation_duration"] = time.time() - evaluation_start
            self._audit_evaluation(results)

        except Exception as e:
            results["error"] = f"Evaluation failed: {str(e)}"
            logging.error(f"[CANARY] Evaluation error: {e}")

        return results

    async def _evaluate_single_canary(
        self,
        canary_name: str,
        weight: float,
        model_metrics: Dict[str, Dict[str, Any]],
        baseline_name: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Evaluate a single canary model's performance."""
        result = {
            "model": canary_name,
            "weight": weight,
            "status": "active",
            "recommendation": "hold",
            "reason": "evaluation_pending",
        }

        canary_stats = model_metrics.get(canary_name, {})
        baseline_stats = model_metrics.get(baseline_name, {})

        # Check minimum requirements
        canary_trades = canary_stats.get("orders_filled", 0)
        baseline_trades = baseline_stats.get("orders_filled", 0)

        if canary_trades < config.get("min_trades_for_eval", 50):
            result.update(
                {
                    "recommendation": "hold",
                    "reason": f'insufficient_trades_{canary_trades}_of_{config["min_trades_for_eval"]}',
                }
            )
            return result

        # Calculate performance metrics
        relative_perf, rating = self.evaluator._calculate_performance_score(
            canary_stats, baseline_stats
        )

        result.update(
            {
                "trades_completed": canary_trades,
                "pnl_realized": canary_stats.get("pnl_realized", 0.0),
                "win_rate": self.evaluator._calculate_win_rate(canary_stats),
                "baseline_trades": baseline_trades,
                "baseline_pnl": baseline_stats.get("pnl_realized", 0.0),
                "relative_performance_pct": relative_perf,
                "statistical_rating": rating,
            }
        )

        # Make recommendation
        if rating == "promotion_candidate":
            result.update(
                {
                    "recommendation": "promote",
                    "reason": f"outperforms_baseline_by_{relative_perf:+.2f}%",
                }
            )
        elif rating == "rollback_candidate":
            result.update(
                {
                    "recommendation": "rollback",
                    "reason": f"underperforms_baseline_by_{relative_perf:+.2f}%",
                }
            )
        elif rating == "insufficient_data":
            result.update(
                {"recommendation": "hold", "reason": "insufficient_data_for_evaluation"}
            )
        else:
            result.update({"recommendation": "hold", "reason": "neutral_performance"})

        return result

    async def _promote_canary(
        self, model_name: str, evaluation: Dict[str, Any], config: Dict[str, Any]
    ):
        """Promote a successful canary to full production."""
        try:
            old_current = config["current"]

            # Update configuration
            config["current"] = model_name
            config["weights"] = {model_name: 1.0}  # Full production weight
            config["last_updated"] = int(time.time())
            config[f"promoted_from_{old_current}_at"] = time.time()

            # Write new configuration
            WEIGHTS_PATH.write_text(json.dumps(config, indent=2))

            logging.info(
                f"[CANARY] 🚀 PROMOTED {model_name}: "
                f"{evaluation['relative_performance_pct']:+.2f}% vs baseline"
            )

            # Notify systems
            try:
                from ops import governance_daemon

                await governance_daemon.BUS.publish(
                    "strategy.canary_promoted",
                    {
                        "promoted_model": model_name,
                        "previous_model": old_current,
                        "performance_advantage": evaluation["relative_performance_pct"],
                        "evaluation": evaluation,
                    },
                )
            except ImportError:
                pass

            # Update registry
            await self._update_registry(model_name, "promoted", evaluation)

            # Update capital allocation policy enabled list
            await self._update_capital_policy_on_promotion(model_name)

        except Exception as e:
            logging.error(f"[CANARY] Promotion failed for {model_name}: {e}")

    async def _rollback_canary(
        self, model_name: str, evaluation: Dict[str, Any], config: Dict[str, Any]
    ):
        """Rollback an underperforming canary."""
        try:
            # Remove canary from rotation
            config["weights"][model_name] = 0.0
            config["last_updated"] = int(time.time())

            WEIGHTS_PATH.write_text(json.dumps(config, indent=2))

            logging.warning(
                f"[CANARY] ❌ ROLLED BACK {model_name}: "
                f"{evaluation['relative_performance_pct']:+.2f}% vs baseline"
            )

            # Notify systems
            try:
                from ops import governance_daemon

                await governance_daemon.BUS.publish(
                    "strategy.canary_rolled_back",
                    {
                        "rolled_back_model": model_name,
                        "performance_deficit": evaluation["relative_performance_pct"],
                        "evaluation": evaluation,
                    },
                )
            except ImportError:
                pass

            # Update registry
            await self._update_registry(model_name, "rolled_back", evaluation)

        except Exception as e:
            logging.error(f"[CANARY] Rollback failed for {model_name}: {e}")

    async def _update_registry(
        self, model_name: str, action: str, evaluation: Dict[str, Any]
    ):
        """Update the strategy registry with canary outcomes."""
        try:
            registry_path = Path("ops/strategy_registry.json")
            if not registry_path.exists():
                registry = {}
            else:
                registry = json.loads(registry_path.read_text())

            if model_name not in registry:
                registry[model_name] = {}

            registry[model_name][f"canary_{action}_at"] = time.time()
            registry[model_name]["last_evaluation"] = evaluation
            registry[model_name]["canary_weight"] = evaluation["weight"]

            registry_path.write_text(json.dumps(registry, indent=2))

        except Exception as e:
            logging.error(f"[CANARY] Registry update failed: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive canary deployment status."""
        config = _load_weights()
        status = {
            "current_model": config.get("current"),
            "active_weights": config.get("weights"),
            "canary_criteria": {
                "min_trades": config.get("min_trades_for_eval"),
                "min_hours": config.get("min_live_hours"),
                "promotion_threshold": config.get("promotion_threshold_pct"),
                "rollback_threshold": config.get("rollback_threshold_pct"),
                "max_canary_weight": config.get("max_canary_weight"),
            },
            "recent_evaluations": self.audit_log[-10:] if self.audit_log else [],
        }

        return status

    async def _update_capital_policy_on_promotion(self, model_name: str):
        """Update capital allocation policy when a model is promoted."""
        try:
            capital_policy_path = Path("ops/capital_policy.json")
            if not capital_policy_path.exists():
                # Create default policy if missing
                default_policy = {
                    "enabled": [model_name],
                    "refresh_sec": 30,
                    "base_equity_frac": 0.20,
                    "min_pool_usd": 10000.0,
                    "reserve_equity_usd": 5000.0,
                    "min_quota_usd": 250.0,
                    "max_quota_usd": 25000.0,
                    "step_up_pct": 0.15,
                    "step_down_pct": 0.20,
                    "sharpe_promote": 1.00,
                    "sharpe_demote": 0.30,
                    "cooldown_sec": 900,
                }
                capital_policy_path.write_text(json.dumps(default_policy, indent=2))
                logging.info(
                    f"[CANARY] Created default capital policy with {model_name} enabled"
                )
                return

            policy = json.loads(capital_policy_path.read_text())

            if model_name not in policy.get("enabled", []):
                enabled = policy.get("enabled", [])
                enabled.append(model_name)
                policy["enabled"] = enabled
                policy["last_updated"] = time.time()

                capital_policy_path.write_text(json.dumps(policy, indent=2))
                logging.info(
                    f"[CANARY] Added {model_name} to capital allocation enabled list"
                )

        except Exception as e:
            logging.error(f"[CANARY] Failed to update capital policy: {e}")

    def _audit_evaluation(self, results: Dict[str, Any]):
        """Audit the evaluation results."""
        self.audit_log.append(results)

        # Keep only recent history
        if len(self.audit_log) > 100:
            self.audit_log = self.audit_log[-100:]

        # Optional: Persist to disk
        try:
            audit_path = Path("ops/logs/canary_audit.jsonl")
            audit_path.parent.mkdir(exist_ok=True)
            with open(audit_path, "a") as f:
                f.write(json.dumps(results) + "\n")
        except Exception as e:
            logging.warning(f"[CANARY] Audit logging failed: {e}")


# Global manager instance
canary_manager = CanaryManager()


async def canary_evaluation_loop(interval_minutes: int = 60):
    """Continuous canary evaluation and action loop."""
    interval_seconds = interval_minutes * 60

    while True:
        try:
            logging.info("[CANARY] 🔬 Starting canary evaluation...")

            # Only evaluate if auto-promotion is enabled
            config = _load_weights()
            if config.get("auto_promotion_enabled", True):
                results = await canary_manager.evaluate_canaries()

                # Log summary
                summary = (
                    f"Evaluated {len(results.get('canaries_evaluated', []))} canaries: "
                    f"{len(results.get('promotions', []))} promoted, "
                    f"{len(results.get('rollbacks', []))} rolled back, "
                    f"{len(results.get('holdings', []))} on hold"
                )

                logging.info(f"[CANARY] {summary}")

                # Emit detailed results as event
                try:
                    from ops import governance_daemon

                    await governance_daemon.BUS.publish(
                        "canary.evaluation_complete", results
                    )
                except ImportError:
                    pass
            else:
                logging.debug("[CANARY] Auto-promotion disabled, skipping evaluation")

        except Exception as e:
            logging.error(f"[CANARY] Evaluation loop error: {e}")

        await asyncio.sleep(interval_seconds)


# Test functions
async def simulate_canary_performance(
    model_name: str = "test_canary", trades: int = 100, pnl: float = 250.0
) -> Dict[str, Any]:
    """Simulate canary performance for testing (injects fake metrics)."""
    # This would normally push test metrics to the metrics endpoint
    # For demo purposes, just log what would happen
    logging.info(f"[CANARY] SIMULATING: {model_name} with {trades} trades, ${pnl} PnL")

    simulated_evaluation = {
        "model": model_name,
        "weight": 0.10,
        "trades_completed": trades,
        "pnl_realized": pnl,
        "win_rate": 0.62,
        "relative_performance_pct": 8.5,
        "statistical_rating": "promotion_candidate",
        "recommendation": "promote",
        "reason": "simulated_performance_data",
    }

    return simulated_evaluation
