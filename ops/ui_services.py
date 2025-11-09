"""Service implementations that back the Command Center UI API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Iterable, Sequence
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

import httpx
import yaml

from ops.env import primary_engine_endpoint

logger = logging.getLogger(__name__)
_JSON_ERRORS = (OSError, json.JSONDecodeError, ValueError)
_PARSE_ERRORS = (TypeError, ValueError)
_COPY_ERRORS = (TypeError, ValueError, RecursionError)
_REQUEST_ERRORS = (httpx.HTTPError, asyncio.TimeoutError, ConnectionError, RuntimeError)
_ENGINE_STATUS_ERRORS = _REQUEST_ERRORS + (ValueError,)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


class PortfolioServiceUnavailableError(RuntimeError):
    """Raised when portfolio service dependency is missing."""

    def __init__(self) -> None:
        super().__init__("portfolio service unavailable")


class EngineCancellationError(RuntimeError):
    """Raised when the engine cannot cancel orders."""


class UnknownRuntimeSettingError(ValueError):
    """Raised when an unknown runtime override key is provided."""

    def __init__(self, key: str) -> None:
        super().__init__(f"unknown runtime setting '{key}'")
        self.key = key


def _ops_control_token() -> str | None:
    token = os.getenv("OPS_API_TOKEN")
    token_file = os.getenv("OPS_API_TOKEN_FILE")
    if token_file:
        try:
            candidate = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read OPS_API_TOKEN_FILE (%s): %s", token_file, exc)
        else:
            if candidate:
                token = candidate
    if token:
        token = token.strip()
    return token or None


def _now() -> float:
    return time.time()


def _deepcopy(value: Any) -> Any:
    try:
        return deepcopy(value)
    except _COPY_ERRORS:  # pragma: no cover - defensive guard
        return json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value


class PortfolioService:
    """Caches the latest account snapshot for UI consumption."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshot: dict[str, Any] = {
            "equity": 0.0,
            "cash": 0.0,
            "exposure": 0.0,
            "pnl": {"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
            "positions": [],
            "ts": 0.0,
            "source": "engine",
        }

    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._snapshot = _deepcopy(snapshot)

    async def list_open_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            return _deepcopy(self._snapshot.get("positions", [])) or []

    async def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return _deepcopy(self._snapshot)


class OrdersService:
    """Maintains a lightweight open-orders cache and proxies cancellation requests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._orders: list[dict[str, Any]] = []
        self._cancel_endpoint = os.getenv("OPS_ENGINE_CANCEL_URL")

    def update_orders(self, orders: Iterable[dict[str, Any]]) -> None:
        with self._lock:
            self._orders = _deepcopy(list(orders))

    async def list_open_orders(self) -> list[dict[str, Any]]:
        with self._lock:
            return _deepcopy(self._orders)

    async def cancel_many(self, order_ids: Sequence[str]) -> dict[str, Any]:
        ids = {str(i) for i in order_ids}
        if self._cancel_endpoint:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.post(self._cancel_endpoint, json={"order_ids": list(ids)})
                    resp.raise_for_status()
                except _REQUEST_ERRORS as exc:
                    raise EngineCancellationError() from exc

        with self._lock:
            before = len(self._orders)
            self._orders = [
                o for o in self._orders if str(o.get("id") or o.get("orderId")) not in ids
            ]
            removed = before - len(self._orders)
        return {"cancelled": list(ids), "removed": removed}


class ConfigService:
    """Exposes runtime configuration state with support for mutable overrides."""

    def __init__(self, base_path: Path, overrides_path: Path) -> None:
        self._base_path = Path(base_path)
        self._overrides_path = Path(overrides_path)
        self._meta_path = self._overrides_path.with_suffix(".meta.json")
        self._audit_path = self._overrides_path.with_suffix(".audit.jsonl")
        self._lock = RLock()
        self._overrides: dict[str, Any] = self._load_overrides()
        self._meta: dict[str, Any] = self._load_meta()

    def _load_base(self) -> dict[str, Any]:
        if not self._base_path.exists():
            return {}
        with self._base_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _load_overrides(self) -> dict[str, Any]:
        if not self._overrides_path.exists():
            return {}
        try:
            return json.loads(self._overrides_path.read_text(encoding="utf-8"))
        except _JSON_ERRORS:  # pragma: no cover - defensive
            logger.warning("Failed to load runtime overrides", exc_info=True)
            return {}

    def _persist(self) -> None:
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self._overrides_path.write_text(
            json.dumps(self._overrides, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _load_meta(self) -> dict[str, Any]:
        if not self._meta_path.exists():
            return {"version": 0, "updated_at": None, "updated_by": None, "approved_by": None}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except _JSON_ERRORS:  # pragma: no cover
            logger.warning("Failed to load runtime meta", exc_info=True)
            return {"version": 0, "updated_at": None, "updated_by": None, "approved_by": None}

    def _persist_meta(self) -> None:
        self._meta_path.write_text(
            json.dumps(self._meta, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _append_audit(self, record: dict[str, Any]) -> None:
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except _JSON_ERRORS:  # pragma: no cover
            logger.warning("Failed to append config audit log", exc_info=True)

    async def get_effective(self) -> dict[str, Any]:
        with self._lock:
            base = self._load_base()
            effective = _deepcopy(base)
            effective.update(self._overrides)
            return {
                "base": base,
                "overrides": _deepcopy(self._overrides),
                "effective": effective,
                "meta": _deepcopy(self._meta),
            }

    async def patch(
        self,
        updates: dict[str, Any],
        *,
        actor: str | None,
        approver: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            base = self._load_base()
            allowed_keys = set(base.keys())
            for key in updates:
                if key not in allowed_keys:
                    raise UnknownRuntimeSettingError(key)
            for key, value in updates.items():
                self._overrides[key] = value
            self._persist()
            effective = _deepcopy(base)
            effective.update(self._overrides)
            self._meta["version"] = int(self._meta.get("version", 0)) + 1
            self._meta["updated_at"] = _now()
            self._meta["updated_by"] = actor
            self._meta["approved_by"] = approver
            self._persist_meta()
            self._append_audit(
                {
                    "ts": self._meta["updated_at"],
                    "version": self._meta["version"],
                    "actor": actor,
                    "approver": approver,
                    "payload": updates,
                }
            )
            return {
                "effective": effective,
                "overrides": _deepcopy(self._overrides),
                "meta": _deepcopy(self._meta),
            }


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = float(sum(float(v) for v in weights.values()))
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: float(v) / total for k, v in weights.items()}


class StrategyGovernanceService:
    """Manages strategy weights and toggle state."""

    def __init__(self, weights_path: Path) -> None:
        self._path = Path(weights_path)
        self._lock = RLock()
        self._disabled_weights: dict[str, float] = {}
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

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except _JSON_ERRORS:  # pragma: no cover - defensive
            logger.exception("Failed to load strategy weights")
            return {"current": "trend_core", "weights": {"trend_core": 1.0}}

    def _save(self, payload: dict[str, Any]) -> None:
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    async def list(self) -> dict[str, Any]:
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

    async def patch(self, strategy_id: str, updates: dict[str, Any]) -> dict[str, Any]:
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
        self._last_refresh: dict[str, float] = {}
        self._alias_map: dict[str, tuple[str, ...]] = {
            "trend": ("trend_core",),
            "momentum": ("momentum_hmm",),
            "scalper": ("scalp_cex",),
            "event": ("event_meme",),
        }
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self._path.exists():
            return
        default = {
            "trend": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            "momentum": ["SOLUSDT", "AVAXUSDT"],
            "event": [],
            "scalper": [],
        }
        self._path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")

    def _load(self) -> dict[str, list[str]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except _JSON_ERRORS:  # pragma: no cover - defensive
            logger.exception("Failed to load universe state")
            return {}

    def _save(self, payload: dict[str, list[str]]) -> None:
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _resolve_key(self, payload: dict[str, list[str]], strategy_id: str) -> str:
        if strategy_id in payload:
            return strategy_id
        for alias in self._alias_map.get(strategy_id, ()):  # migrate legacy keys
            if alias in payload:
                payload[strategy_id] = payload.pop(alias)
                self._save(payload)
                return strategy_id
        return strategy_id

    async def universe(self, strategy_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            key = self._resolve_key(payload, strategy_id)
            symbols = payload.get(key, [])
            return {
                "strategy": strategy_id,
                "symbols": symbols,
                "last_refresh": self._last_refresh.get(strategy_id),
            }

    async def refresh(self, strategy_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            key = self._resolve_key(payload, strategy_id)
            # Refresh is currently a no-op placeholder; we simply timestamp it.
            self._last_refresh[strategy_id] = _now()
            if key != strategy_id and strategy_id not in payload:
                payload[strategy_id] = payload.get(key, [])
            self._save(payload)
            return {
                "strategy": strategy_id,
                "last_refresh": self._last_refresh[strategy_id],
            }


class RiskGuardService:
    """Tracks ad-hoc soft-breach triggers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._last_trigger: float | None = None

    async def soft_breach_now(self) -> dict[str, Any]:
        with self._lock:
            self._last_trigger = _now()
            return {"ok": True, "triggered_at": self._last_trigger}


class FeedsGovernanceService:
    """Stores lightweight feed control state for announcements/meme feeds."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state: dict[str, Any] = {
            "announcements": {"enabled": True},
            "meme": {"enabled": False},
        }

    async def status(self) -> dict[str, Any]:
        with self._lock:
            return _deepcopy(self._state)

    async def patch_announcements(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state["announcements"].update(payload)
            self._state["announcements"]["updated_at"] = _now()
            return _deepcopy(self._state["announcements"])

    async def patch_meme(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        portfolio_service: PortfolioService | None = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._engine_status_fn = engine_status_fn
        self._portfolio_service = portfolio_service
        self._lock = RLock()
        self._boot = _now()

    def _load_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {"trading_enabled": True}
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except _JSON_ERRORS:  # pragma: no cover - defensive
            return {"trading_enabled": True}

    def _persist(self, state: dict[str, Any]) -> None:
        self._state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    async def status(self) -> dict[str, Any]:
        state = self._load_state()
        trading_enabled = bool(state.get("trading_enabled", True))
        try:
            engine_info = await self._engine_status_fn()
        except _ENGINE_STATUS_ERRORS as exc:
            engine_info = {"ok": False, "error": str(exc)}

        account_snapshot: dict[str, Any] | None = None
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

    async def set_trading_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
            state["trading_enabled"] = bool(enabled)
            self._persist(state)

        endpoint = primary_engine_endpoint()
        headers: dict[str, str] = {}
        token = _ops_control_token()
        if token:
            headers["X-Ops-Token"] = token

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(
                    f"{endpoint}/ops/trading",
                    json={"enabled": bool(enabled)},
                    headers=headers or None,
                )
                resp.raise_for_status()
        except _REQUEST_ERRORS as exc:
            logger.warning("Engine trading toggle failed: %s", exc)

        return {"trading_enabled": bool(enabled), "ts": _now()}

    async def flatten_positions(self, actor: str | None = None) -> dict[str, Any]:
        if self._portfolio_service is None:
            raise PortfolioServiceUnavailableError()

        endpoint = primary_engine_endpoint()
        async with httpx.AsyncClient(timeout=12.0) as client:
            positions: list[dict[str, Any]] = []
            try:
                resp = await client.get(f"{endpoint}/portfolio")
                resp.raise_for_status()
                payload = resp.json() or {}
                positions = (
                    payload.get("positions") or payload.get("state", {}).get("positions", []) or []
                )
            except _REQUEST_ERRORS as exc:
                logger.warning("Engine portfolio fetch failed: %s", exc)
                positions = []

            if not positions:
                positions = await self._portfolio_service.list_open_positions()

            targets: list[dict[str, Any]] = []
            for pos in positions:
                try:
                    qty = float(pos.get("qty") or pos.get("qty_base") or 0.0)
                except _PARSE_ERRORS:
                    qty = 0.0
                if abs(qty) <= 0.0:
                    continue
                symbol = str(pos.get("symbol") or "").strip()
                if not symbol:
                    continue
                targets.append({"symbol": symbol, "qty": qty})

            if not targets:
                return {
                    "flattened": [],
                    "requested": 0,
                    "succeeded": 0,
                    "actor": actor,
                }

            flattened: list[dict[str, Any]] = []
            succeeded = 0

            for target in targets:
                qty = float(target["qty"])
                side = "SELL" if qty > 0 else "BUY"
                symbol = target["symbol"]
                venue = os.getenv("VENUE", "BINANCE").upper()
                if "." not in symbol and venue:
                    symbol = f"{symbol}.{venue}"
                payload = {
                    "symbol": symbol,
                    "side": side,
                    "quantity": abs(qty),
                }
                headers = {"X-Idempotency-Key": uuid.uuid4().hex}
                try:
                    resp = await client.post(
                        f"{endpoint}/orders/market",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    flattened.append(
                        {
                            "symbol": symbol,
                            "side": side,
                            "quantity": abs(qty),
                            "order": resp.json(),
                        }
                    )
                    succeeded += 1
                except _REQUEST_ERRORS as exc:
                    _log_suppressed("ops.flatten", exc)
                    flattened.append(
                        {
                            "symbol": symbol,
                            "side": side,
                            "quantity": abs(qty),
                            "error": str(exc),
                        }
                    )

        return {
            "flattened": flattened,
            "requested": len(targets),
            "succeeded": succeeded,
            "actor": actor,
        }

    async def transfer_internal(
        self, asset: str, amount: float, source: str, target: str
    ) -> dict[str, Any]:
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
