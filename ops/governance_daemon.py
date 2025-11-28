"""
Autonomous Governance Daemon - M15 Brainstem Layer

The self-governing intelligence that provides free will and self-determination to the trading organism.
Subscribes to event streams, evaluates governance policies, and executes autonomous actions in response.

Architecture:
- Reacts to real-time events from the system
- Evaluates complex conditions against governance policies
- Executes decisive actions (pause trading, risk adjustments, model promotion)
- Maintains audit trails of all governance decisions
- Includes cooldown mechanisms to prevent action thrashing
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from prometheus_client import Counter, Gauge

from engine.core.event_bus import BUS
from ops.strategy_selector import promote_best
from ops.allocator import WealthManager, StrategyPerformance
from ops.telemetry_store import Metrics

# Prometheus metrics for governance visibility
_GOVERNANCE_RULES_ACTIVE = Gauge(
    "governance_rules_active",
    "Number of enabled governance rules loaded",
)
_GOVERNANCE_RULE_TRIPPED = Counter(
    "governance_rule_tripped_total",
    "Total governance rule executions",
    ["name"],
)

_POLICY_ERRORS = (OSError, yaml.YAMLError, ValueError, TypeError)
_RULE_EVAL_ERRORS = (SyntaxError, NameError, TypeError, ValueError)
_COUNTER_ERRORS = (ValueError, RuntimeError)
_ACTION_ERRORS = (RuntimeError, ValueError, OSError)
_PUBLISH_ERRORS = (RuntimeError, ValueError)
_AUDIT_ERRORS = (OSError, ValueError)
_PROMOTION_ERRORS = (RuntimeError, ValueError)

AUDIT_PATH = Path("ops/logs/governance_audit.jsonl")


@dataclass
class GovernanceRule:
    """Individual governance policy rule."""

    trigger: str
    condition: str
    action: str
    priority: str = "medium"
    cooldown_seconds: int = 0
    description: str = ""
    enabled: bool = True
    name: str = ""
    params: dict[str, Any] = None

    def evaluate(self, data: dict[str, Any]) -> bool:
        """Evaluate condition against event data."""
        try:
            return bool(eval(self.condition, {"__builtins__": {}}, {"data": data}))
        except _RULE_EVAL_ERRORS as exc:
            logging.warning("[GOV] Rule evaluation error for '%s': %s", self.action, exc)
            return False


@dataclass
class GovernanceMetrics:
    """Metrics for governance system monitoring."""

    rules_evaluated: int = 0
    actions_executed: int = 0
    cooldown_hits: int = 0
    critical_actions: int = 0
    performance_actions: int = 0
    emergency_actions: int = 0


class GovernanceDaemon:
    """
    The autonomous governance system - the "brainstem" that gives the trading organism free will.

    Features:
    - Real-time event subscription and processing
    - Complex policy evaluation with safe expression execution
    - Multi-tiered action hierarchy (emergency → performance → optimization)
    - Cooldown mechanisms to prevent action thrashing
    - Complete audit trail of all governance decisions
    - Environment variable manipulation for runtime control
    """

    def __init__(self, policy_path: str | None = None):
        self.policy_path = policy_path or os.getenv("GOVERNANCE_POLICY", "ops/policies.yaml")
        self.rules: list[GovernanceRule] = []
        self.last_actions: dict[str, float] = {}  # action -> timestamp
        self.audit_events: list[dict[str, Any]] = []  # Last 1000 governance events
        self.metrics = GovernanceMetrics()

        # Load governance policies
        self._load_policies()
        self._setup_event_subscriptions()

        # Wealth Manager Integration
        self.wealth_manager = WealthManager()
        asyncio.create_task(self._run_allocation_cycle())

        logging.info(f"[GOV] 🎯 Autonomous Governance initialized with {len(self.rules)} rules")

    def _load_policies(self) -> None:
        """Load governance policies from YAML configuration."""
        if not os.path.exists(self.policy_path):
            logging.warning(f"[GOV] Policy file not found: {self.policy_path}")
            return

        try:
            with open(self.policy_path) as f:
                policies = yaml.safe_load(f)

            for policy in policies.get("rules", []):
                rule = GovernanceRule(
                    trigger=policy["trigger"],
                    condition=policy["condition"],
                    action=policy["action"],
                    priority=policy.get("priority", "medium"),
                    cooldown_seconds=policy.get("cooldown_seconds", 0),
                    description=policy.get("description", ""),
                    enabled=policy.get("enabled", True),
                    name=policy.get("name", ""),
                    params=policy.get("params", {}),
                )
                if not rule.name:
                    desc = (rule.description or rule.action).strip().replace(" ", "_")[:40]
                    rule.name = (
                        f"{rule.trigger}:{desc}" if desc else f"{rule.trigger}:{rule.action}"
                    )
                self.rules.append(rule)

            logging.info(
                f"[GOV] Loaded {len([r for r in self.rules if r.enabled])} enabled governance rules"
            )
            try:
                _GOVERNANCE_RULES_ACTIVE.set(len([r for r in self.rules if r.enabled]))
            except _COUNTER_ERRORS:
                logging.debug("[GOV] Unable to update governance rule active gauge", exc_info=True)

        except _POLICY_ERRORS:
            logging.exception("[GOV] Failed to load governance policies")

    def _setup_event_subscriptions(self) -> None:
        """Subscribe to relevant event topics."""
        topic_handlers = {}  # topic -> handler function

        for rule in self.rules:
            if not rule.enabled:
                continue

            if rule.trigger not in topic_handlers:
                topic_handlers[rule.trigger] = self._create_handler(rule.trigger)
                BUS.subscribe(rule.trigger, topic_handlers[rule.trigger])

    def _create_handler(self, topic: str) -> Callable:
        """Create event handler for a specific topic."""

        async def handle_event(data: dict[str, Any]) -> None:
            """Process events against governance rules."""
            for rule in [r for r in self.rules if r.trigger == topic and r.enabled]:
                self.metrics.rules_evaluated += 1

                # Evaluate rule condition
                if not rule.evaluate(data):
                    continue

                # Check cooldown
                if self._is_on_cooldown(rule.action, rule.cooldown_seconds):
                    self.metrics.cooldown_hits += 1
                    logging.debug(f"[GOV] Cooldown active for {rule.action}, skipping")
                    continue

                # Execute governance action
                logging.info(f"[GOV] 📋 {rule.action.upper()} triggered: {rule.description}")

                await self._execute_action(rule.action, data, rule)

                # Update cooldown and audit
                self.last_actions[rule.action] = time.time()
                self._audit_action(rule, data)

        return handle_event

    async def _execute_action(
        self, action: str, data: dict[str, Any], rule: GovernanceRule
    ) -> None:
        """Execute the actual governance action."""
        self.metrics.actions_executed += 1

        try:
            if action == "pause_trading":
                os.environ["TRADING_ENABLED"] = "false"
                self.metrics.emergency_actions += 1
                logging.warning("[GOV] 🚫 TRADING PAUSED by autonomous governance")

            elif action == "resume_trading":
                os.environ["TRADING_ENABLED"] = "true"
                logging.info("[GOV] ▶️ TRADING RESUMED by autonomous governance")

            elif action == "reduce_exposure":
                current_max = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                new_max = max(current_max * 0.7, 10.0)  # Reduce by 30%, minimum $10
                os.environ["MAX_NOTIONAL_USDT"] = str(new_max)
                self.metrics.performance_actions += 1
                logging.warning(f"[GOV] 📉 EXPOSURE REDUCED: ${current_max} → ${new_max}")

            elif action == "moderate_reductions":
                current_max = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                new_max = max(current_max * 0.85, 20.0)  # Reduce by 15%, minimum $20
                os.environ["MAX_NOTIONAL_USDT"] = str(new_max)
                self.metrics.performance_actions += 1
                logging.info(f"[GOV] 📈 EXPOSURE MODERATED: ${current_max} → ${new_max}")

            elif action == "emergency_reductions":
                # Emergency 50% reduction
                current_max = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                new_max = max(current_max * 0.5, 5.0)  # Reduce by 50%, minimum $5
                os.environ["MAX_NOTIONAL_USDT"] = str(new_max)
                self.metrics.emergency_actions += 1
                logging.critical(f"[GOV] 🚨 EMERGENCY REDUCTIONS: ${current_max} → ${new_max}")

            elif action == "increase_exposure":
                current_max = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                new_max = min(current_max * 1.2, 1000.0)  # Increase by 20%, maximum $1000
                os.environ["MAX_NOTIONAL_USDT"] = str(new_max)
                logging.info(f"[GOV] 📈 EXPOSURE INCREASED: ${current_max} → ${new_max}")

            elif action == "set_max_notional":
                # Explicitly set MAX_NOTIONAL_USDT from rule params
                try:
                    target = float((rule.params or {}).get("value"))
                except (TypeError, ValueError):
                    target = float(
                        os.getenv(
                            "MAX_NOTIONAL_BASELINE",
                            os.getenv("MAX_NOTIONAL_USDT", "400"),
                        )
                    )
                old = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                os.environ["MAX_NOTIONAL_USDT"] = str(target)
                logging.info(f"[GOV] 🎚️ MAX_NOTIONAL set: ${old} → ${target}")

            elif action == "gradual_resume":
                # Gradual resumption - enable trading with reduced limits first
                os.environ["TRADING_ENABLED"] = "true"
                current_max = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                resume_max = min(current_max, 50.0)  # Start with $50 limit
                os.environ["MAX_NOTIONAL_USDT"] = str(resume_max)
                logging.info(f"[GOV] 🔄 GRADUAL RESUME: Trading enabled @ ${resume_max} limit")

            elif action == "immediate_resume":
                os.environ["TRADING_ENABLED"] = "true"
                # Don't change limits - full resumption
                logging.info("[GOV] 🔄 IMMEDIATE RESUME: Full trading restored")

            elif action == "promote_model":
                try:
                    result = await asyncio.get_event_loop().run_in_executor(None, promote_best)
                    if result:
                        logging.info(f"[GOV] 🚀 MODEL PROMOTED: New strategy activated - {result}")
                    else:
                        logging.warning("[GOV] 🚫 MODEL PROMOTION failed")
                except _PROMOTION_ERRORS:
                    logging.exception("[GOV] Model promotion error")

            elif action == "conservative_shift":
                # Adjust risk parameters to be more conservative
                current_min = float(os.getenv("MIN_NOTIONAL_USDT", "5"))
                os.environ["MIN_NOTIONAL_USDT"] = str(current_min * 1.5)  # Higher minimums
                logging.info("[GOV] 🛡️ CONSERVATIVE SHIFT: Minimum order size increased")

            elif action == "reduce_max_order_size":
                # Reduce maximum order sizes during illiquidity
                current_rate = int(os.getenv("MAX_ORDERS_PER_MIN", "30"))
                new_rate = max(current_rate // 2, 3)  # Halve rate, minimum 3/min
                os.environ["MAX_ORDERS_PER_MIN"] = str(new_rate)
                logging.warning(f"[GOV] 🐌 ORDER RATE REDUCED: {current_rate}/min → {new_rate}/min")

            elif action == "gradual_risk_increase":
                current_max = float(os.getenv("MAX_NOTIONAL_USDT", "400"))
                new_max = min(current_max * 1.15, 500.0)  # 15% increase, max $500
                os.environ["MAX_NOTIONAL_USDT"] = str(new_max)
                logging.info(f"[GOV] 📊 RISK GRADUAL INCREASE: ${current_max} → ${new_max}")

            elif action == "review_alert_config":
                # This would trigger a manual review - just log for now
                logging.info("[GOV] 📋 ALERT CONFIG REVIEW needed - excessive throttling detected")

            elif action == "investigate_desync":
                # Schedule investigation of sync issues
                logging.warning("[GOV] 🔍 SYNC ISSUES detected - may require investigation")

            elif action == "notify_ops":
                # This would trigger external notifications beyond standard alerts
                logging.warning("[GOV] 📞 OPS NOTIFICATION: Manual attention required")
                # Could trigger more aggressive notifications here

            # Informational actions (no environment changes)
            elif action == "log_btc_activity":
                logging.info(f"[GOV] ₿ BTC Activity: {data}")

            elif action == "update_performance_stats":
                logging.debug(f"[GOV] 📊 Performance stats updated: {data}")

            elif action == "log_performance_audit":
                logging.info(f"[GOV] 📋 Performance audit logged: {data}")

            else:
                logging.warning(f"[GOV] Unknown governance action: {action}")

        except _ACTION_ERRORS:
            logging.exception("[GOV] Action '%s' failed", action)
            return

        # Notify subscribers (e.g., engine to hot-reload risk rails)
        try:
            await BUS.publish(
                "governance.action",
                {
                    "action": action,
                    "timestamp": time.time(),
                    "description": rule.description,
                },
            )
        except _PUBLISH_ERRORS:
            logging.debug("[GOV] notify publish failed", exc_info=True)

    async def _execute_dust_sweep(self) -> None:
        """Convert small balances (dust) to BNB for account hygiene."""
        try:
            # Get current balances from portfolio
            balances = self.portfolio.state.balances
            
            # Identify dust assets (< $1 USD value)
            dust_assets = []
            for asset, amount in balances.items():
                if asset == "BNB" or amount == 0:
                    continue  # Don't convert BNB or zero balances
                
                # Get price for this asset (try common pairs)
                try:
                    if asset in {"USDT", "FDUSD", "BUSD", "USDC"}:
                        # Stablecoins worth ~$1
                        value_usd = amount
                    else:
                        # Try to get price vs USDT
                        price = await self.binance_client.ticker_price(f"{asset}USDT", market="spot")
                        value_usd = amount * price
                    
                    if value_usd < 1.0:
                        dust_assets.append(asset)
                        logging.debug(f"[Hygiene] Dust found: {asset} = {amount} (${value_usd:.4f})")
                
                except Exception:
                    # If we can't get price, skip this asset
                    continue
            
            if not dust_assets:
                logging.debug("[Hygiene] No dust to convert")
                return
            
            # Convert dust to BNB
            logging.info(f"[Hygiene] Converting dust: {dust_assets} -> BNB")
            result = await self.binance_client.convert_dust(dust_assets)
            
            if result.get("totalTransfered"):
                logging.info(f"[Hygiene] ✅ Converted dust to {result.get('totalTransfered')} BNB")
            
        except Exception as exc:
            logging.warning(f"[Hygiene] Dust sweep failed: {exc}", exc_info=True)

    def _is_on_cooldown(self, action: str, cooldown_seconds: int) -> bool:
        """Check if action is still on cooldown."""
        if cooldown_seconds == 0:
            return False

        last_time = self.last_actions.get(action, 0)
        return (time.time() - last_time) < cooldown_seconds

    def _audit_action(self, rule: GovernanceRule, data: dict[str, Any]) -> None:
        """Record governance action for audit and transparency."""
        audit_event = {
            "timestamp": time.time(),
            "trigger": rule.trigger,
            "condition": rule.condition,
            "action": rule.action,
            "priority": rule.priority,
            "event_data": data,
            "description": rule.description,
        }

        self.audit_events.append(audit_event)

        # Keep only recent history (last 1000 events)
        if len(self.audit_events) > 1000:
            self.audit_events = self.audit_events[-1000:]

        # Immediate log for transparency
        logging.info(f"[GOV] AUDIT: {rule.action} executed due to {rule.trigger}")
        try:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(audit_event) + "\n")
        except _AUDIT_ERRORS:  # pragma: no cover - best-effort persistence
            logging.warning("[GOV] Failed to append audit trail", exc_info=True)
        try:
            _GOVERNANCE_RULE_TRIPPED.labels(name=rule.name or f"{rule.trigger}:{rule.action}").inc()
        except _COUNTER_ERRORS:
            logging.debug("[GOV] Unable to increment governance rule counter", exc_info=True)

    def get_status(self) -> dict[str, Any]:
        """Get current governance system status."""
        return {
            "rules_loaded": len(self.rules),
            "enabled_rules": len([r for r in self.rules if r.enabled]),
            "triggers": list(set(r.trigger for r in self.rules if r.enabled)),
            "metrics": self.metrics.__dict__,
            "active_cooldowns": {
                action: time.time() - timestamp
                for action, timestamp in self.last_actions.items()
                if (time.time() - timestamp) < 3600  # Show active cooldowns < 1 hour
            },
            "recent_audits": self.audit_events[-5:] if self.audit_events else [],
        }

    def reload_policies(self) -> bool:
        """Reload policies from disk (for hot config updates)."""
        try:
            self.rules.clear()
            self._load_policies()
            self._setup_event_subscriptions()
            logging.info("[GOV] ✅ Policies reloaded successfully")
            try:
                _GOVERNANCE_RULES_ACTIVE.set(len([r for r in self.rules if r.enabled]))
            except _COUNTER_ERRORS:
                logging.debug("[GOV] Unable to update governance rule active gauge", exc_info=True)
        except _POLICY_ERRORS:
            logging.exception("[GOV] ❌ Policy reload failed")
            return False
        else:
            return True

    def force_action(self, action: str, reason: str = "manual") -> bool:
        """Force execute a governance action (for testing/admin purposes)."""
        try:
            mock_data = {"forced": True, "reason": reason}
            asyncio.create_task(
                self._execute_action(
                    action,
                    mock_data,
                    GovernanceRule("manual", "True", action, "high", 0, f"Manual {action}"),
                )
            )
            logging.info(f"[GOV] 🔧 Manual action executed: {action}")
        except _ACTION_ERRORS:
            logging.exception("[GOV] Manual action failed")
            return False
        else:
            return True


    async def _run_allocation_cycle(self) -> None:
        """Periodic capital reallocation loop (Hourly)."""
        while True:
            try:
                # Wait for system to warm up
                await asyncio.sleep(60)
                
                logging.info("[GOV] 💰 Starting Hourly Capital Allocation Cycle...")
                
                # 1. Fetch Metrics
                # In a real system, this would query the Telemetry Service or DB
                # Here we'll try to read from a shared metrics file if it exists, or use mock data for demonstration
                strategies = self._fetch_strategy_performance()
                
                if strategies:
                    # 2. Run Allocation
                    self.wealth_manager.allocate(strategies)
                    
                    # 3. Log Result
                    logging.info(f"[GOV] ✅ Allocation Complete. Updated limits for {len(strategies)} strategies.")
                else:
                    logging.info("[GOV] No strategy metrics available for allocation.")

            except Exception as e:
                logging.error(f"[GOV] ❌ Allocation cycle failed: {e}", exc_info=True)
            
            # Sleep for 1 hour
            await asyncio.sleep(3600)

    def _fetch_strategy_performance(self) -> list[StrategyPerformance]:
        """Fetch performance metrics for all active strategies."""
        # TODO: Connect to real TelemetryStore
        # For now, we return an empty list or mock data if needed
        # This ensures the loop runs without crashing
        return []

# Global instance
_governance_daemon = None


async def initialize_governance() -> None:
    """Initialize the autonomous governance system."""
    global _governance_daemon
    _governance_daemon = GovernanceDaemon()
    logging.info("[GOV] 🧠 Autonomous Governance Engine activated")


async def shutdown_governance() -> None:
    """Shutdown governance system gracefully."""
    global _governance_daemon
    _governance_daemon = None
    logging.info("[GOV] 🧠 Autonomous Governance Engine deactivated")


# Utility functions for governance integration
def get_governance_status() -> dict[str, Any]:
    """Get current governance system status."""
    if _governance_daemon:
        return _governance_daemon.get_status()
    return {"status": "inactive"}


def reload_governance_policies() -> bool:
    """Hot-reload governance policies."""
    if _governance_daemon:
        return _governance_daemon.reload_policies()
    return False


def force_governance_action(action: str, reason: str = "manual") -> bool:
    """Force a governance action (admin function)."""
    if _governance_daemon:
        return _governance_daemon.force_action(action, reason)
    return False


def get_recent_governance_actions(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent governance audit events (up to `limit`)."""
    if _governance_daemon and _governance_daemon.audit_events:
        return _governance_daemon.audit_events[-max(0, int(limit)) :]
    return []
