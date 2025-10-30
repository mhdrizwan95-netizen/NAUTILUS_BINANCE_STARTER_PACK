"""Service implementations that back the Command Center UI API."""
from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx
import yaml

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


def _deepcopy(value: Any) -> Any:
    try:
        return deepcopy(value)
    except Exception:  # pragma: no cover - defensive guard
        return json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value


class PortfolioService:
    """Caches the latest account snapshot for UI consumption."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshot: Dict[str, Any] = {
            "equity": 0.0,
            "cash": 0.0,
            "exposure": 0.0,
            "pnl": {"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
            "positions": [],
            "ts": 0.0,
            "source": "engine",
        }

    def update_snapshot(self, snapshot: Dict[str, Any]) -> None:
        with self._lock:
            self._snapshot = _deepcopy(snapshot)

    async def list_open_positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return _deepcopy(self._snapshot.get("positions", [])) or []

    async def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return _deepcopy(self._snapshot)


class OrdersService:
    """Maintains a lightweight open-orders cache and proxies cancellation requests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._orders: List[Dict[str, Any]] = []
        self._cancel_endpoint = os.getenv("OPS_ENGINE_CANCEL_URL")

    def update_orders(self, orders: Iterable[Dict[str, Any]]) -> None:
        with self._lock:
            self._orders = _deepcopy(list(orders))

    async def list_open_orders(self) -> List[Dict[str, Any]]:
        with self._lock:
            return _deepcopy(self._orders)

    async def cancel_many(self, order_ids: Sequence[str]) -> Dict[str, Any]:
        ids = {str(i) for i in order_ids}
        if self._cancel_endpoint:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.post(self._cancel_endpoint, json={"order_ids": list(ids)})
                    resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"engine cancellation failed: {exc}") from exc

        with self._lock:
            before = len(self._orders)
            self._orders = [
                o
                for o in self._orders
                if str(o.get("id") or o.get("orderId")) not in ids
            ]
            removed = before - len(self._orders)
        return {"cancelled": list(ids), "removed": removed}


class ConfigService:
    """Exposes runtime configuration state with support for mutable overrides."""

    def __init__(self, base_path: Path, overrides_path: Path) -> None:
        self._base_path = Path(base_path)
        self._overrides_path = Path(overrides_path)
        self._lock = RLock()
        self._overrides: Dict[str, Any] = self._load_overrides()

    def _load_base(self) -> Dict[str, Any]:
        if not self._base_path.exists():
            return {}
        with self._base_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _load_overrides(self) -> Dict[str, Any]:
        if not self._overrides_path.exists():
            return {}
        try:
            return json.loads(self._overrides_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load runtime overrides: %s", exc)
            return {}

    def _persist(self) -> None:
        self._overrides_path.write_text(
            json.dumps(self._overrides, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    async def get_effective(self) -> Dict[str, Any]:
        with self._lock:
            base = self._load_base()
            effective = _deepcopy(base)
            effective.update(self._overrides)
            return {
                "base": base,
                "overrides": _deepcopy(self._overrides),
                "effective": effective,
            }

    async def patch(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            for key, value in updates.items():
                self._overrides[key] = value
            self._persist()
            base = self._load_base()
            effective = _deepcopy(base)
            effective.update(self._overrides)
            return {
                "effective": effective,
                "overrides": _deepcopy(self._overrides),
            }


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = float(sum(float(v) for v in weights.values()))
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: float(v) / total for k, v in weights.items()}


class StrategyGovernanceService:
    """Manages strategy weights and toggle state."""

    def __init__(self, weights_path: Path) -> None:
        self._path = Path(weights_path)
        self._lock = RLock()
        self._disabled_weights: Dict[str, float] = {}
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self._path.exists():
            return
        default_payload = {
            "current": "trend_core",
            "weights": {
                "trend_core": 1.0,
            },
        }
        self._path.write_text(json.dumps(default_payload, indent=2), encoding="utf-8")

    def _load(self) -> Dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to load strategy weights: %s", exc)
            return {"current": "trend_core", "weights": {"trend_core": 1.0}}

    def _save(self, payload: Dict[str, Any]) -> None:
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    async def list(self) -> Dict[str, Any]:
        with self._lock:
            payload = self._load()
        weights = payload.get("weights", {})
        items = [
            {
                "id": name,
                "weight": float(weight),
                "enabled": float(weight) > 0.0,
                "is_current": name == payload.get("current"),
            }
            for name, weight in weights.items()
        ]
        return {
            "current": payload.get("current"),
            "strategies": items,
            "updated_at": _now(),
        }

    async def patch(self, strategy_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            payload = self._load()
            weights = payload.setdefault("weights", {})
            if "weights" in updates and isinstance(updates["weights"], dict):
                incoming = {k: float(v) for k, v in updates["weights"].items()}
                for key, value in incoming.items():
                    weights[key] = value
                    if value > 0:
                        self._disabled_weights.pop(key, None)
                weights = _normalize_weights(weights)
                payload["weights"] = weights

            if "enabled" in updates:
                enabled = bool(updates["enabled"])
                current_weight = float(weights.get(strategy_id, 0.0))
                if enabled:
                    if current_weight <= 0.0:
                        restored = self._disabled_weights.pop(strategy_id, None) or 1.0
                        weights[strategy_id] = restored
                        payload["weights"] = _normalize_weights(weights)
                else:
                    if current_weight > 0.0:
                        self._disabled_weights[strategy_id] = current_weight
                    weights[strategy_id] = 0.0
                    payload["weights"] = _normalize_weights(weights)

            if strategy_id and payload.get("current") not in weights:
                payload["current"] = strategy_id

            self._save(payload)
            return await self.list()


class ScannerService:
    """Provides dynamic universe snapshots with manual refresh hooks."""

    def __init__(self, state_path: Path) -> None:
        self._path = Path(state_path)
        self._lock = RLock()
        self._last_refresh: Dict[str, float] = {}
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self._path.exists():
            return
        default = {
            "trend_core": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            "momentum_hmm": ["SOLUSDT", "AVAXUSDT"],
            "event_meme": [],
            "scalp_cex": [],
        }
        self._path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")

    def _load(self) -> Dict[str, List[str]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to load universe state: %s", exc)
            return {}

    def _save(self, payload: Dict[str, List[str]]) -> None:
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    async def universe(self, strategy_id: str) -> Dict[str, Any]:
        with self._lock:
            payload = self._load()
            symbols = payload.get(strategy_id, [])
            return {
                "strategy": strategy_id,
                "symbols": symbols,
                "last_refresh": self._last_refresh.get(strategy_id),
            }

    async def refresh(self, strategy_id: str) -> Dict[str, Any]:
        with self._lock:
            payload = self._load()
            # Refresh is currently a no-op placeholder; we simply timestamp it.
            self._last_refresh[strategy_id] = _now()
            self._save(payload)
            return {
                "strategy": strategy_id,
                "last_refresh": self._last_refresh[strategy_id],
            }


class RiskGuardService:
    """Tracks ad-hoc soft-breach triggers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._last_trigger: Optional[float] = None

    async def soft_breach_now(self) -> Dict[str, Any]:
        with self._lock:
            self._last_trigger = _now()
            return {"ok": True, "triggered_at": self._last_trigger}


class FeedsGovernanceService:
    """Stores lightweight feed control state for announcements/meme feeds."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state: Dict[str, Any] = {
            "announcements": {"enabled": True},
            "meme": {"enabled": False},
        }

    async def status(self) -> Dict[str, Any]:
        with self._lock:
            return _deepcopy(self._state)

    async def patch_announcements(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._state["announcements"].update(payload)
            self._state["announcements"]["updated_at"] = _now()
            return _deepcopy(self._state["announcements"])

    async def patch_meme(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._state["meme"].update(payload)
            self._state["meme"]["updated_at"] = _now()
            return _deepcopy(self._state["meme"])


class OpsGovernanceService:
    """Aggregates engine status, trading flags, and manual controls."""

    def __init__(
        self,
        state_path: Path,
        engine_status_fn,
        portfolio_service: Optional[PortfolioService] = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._engine_status_fn = engine_status_fn
        self._portfolio_service = portfolio_service
        self._lock = RLock()
        self._boot = _now()

    def _load_state(self) -> Dict[str, Any]:
        if not self._state_path.exists():
            return {"trading_enabled": True}
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover - defensive
            return {"trading_enabled": True}

    def _persist(self, state: Dict[str, Any]) -> None:
        self._state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    async def status(self) -> Dict[str, Any]:
        state = self._load_state()
        trading_enabled = bool(state.get("trading_enabled", True))
        try:
            engine_info = await self._engine_status_fn()
        except Exception as exc:  # noqa: BLE001
            engine_info = {"ok": False, "error": str(exc)}

        account_snapshot: Optional[Dict[str, Any]] = None
        if self._portfolio_service is not None:
            account_snapshot = await self._portfolio_service.snapshot()

        return {
            "trading_enabled": trading_enabled,
            "engine": engine_info,
            "account": account_snapshot,
            "uptime_seconds": _now() - self._boot,
            "features": {
                "binance_only": True,
                "ibkr_beta": False,
            },
        }

    async def set_trading_enabled(self, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            state["trading_enabled"] = bool(enabled)
            self._persist(state)
            return {"trading_enabled": state["trading_enabled"], "ts": _now()}

    async def transfer_internal(self, asset: str, amount: float, source: str, target: str) -> Dict[str, Any]:
        # This implementation simply logs the intent; integration with the venue API can be
        # added later without changing the UI contract.
        logger.info(
            "Requested internal transfer asset=%s amount=%s source=%s target=%s",
            asset,
            amount,
            source,
            target,
        )
        return {
            "ok": True,
            "asset": asset,
            "amount": amount,
            "source": source,
            "target": target,
            "ts": _now(),
        }
