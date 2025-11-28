from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)


def _norm_strategy(strategy: str) -> str:
    return strategy.strip().lower()


def _norm_instrument(instrument: str) -> str:
    return instrument.upper().split(".")[0]


def _flatten_features(features: dict[str, float]) -> dict[str, float]:
    return {f"features[{key}]": float(value) for key, value in features.items()}


@dataclass
class _WatchConfig:
    strategy: str
    instrument: str
    features: dict[str, float] = field(default_factory=lambda: {"bias": 1.0})


class ParamOutcomeTracker:
    """Tracks per-strategy positions to compute realized PnL for closed legs."""

    def __init__(self) -> None:
        self._positions: dict[tuple[str, str, str], dict[str, float]] = {}

    def process(
        self,
        strategy: str,
        instrument: str,
        preset_id: str,
        side: str,
        quantity: float,
        price: float,
    ) -> float:
        if quantity <= 0 or price <= 0:
            return 0.0
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            return 0.0

        key = (strategy, instrument, preset_id)
        state = self._positions.setdefault(key, {"qty": 0.0, "avg": 0.0})
        prev_qty = state["qty"]
        prev_avg = state["avg"]

        signed_qty = quantity if side == "BUY" else -quantity
        realized = 0.0

        if prev_qty == 0 or (prev_qty > 0 and signed_qty > 0) or (prev_qty < 0 and signed_qty < 0):
            # Adding to an existing position or opening a new one
            new_qty = prev_qty + signed_qty
            total_abs = abs(prev_qty) + abs(signed_qty)
            weighted = prev_avg * abs(prev_qty) + price * abs(signed_qty)
            state["qty"] = new_qty
            state["avg"] = weighted / total_abs if total_abs > 0 else 0.0
            return 0.0

        # Closing or flipping the position
        closing_qty = min(abs(prev_qty), abs(signed_qty))
        if closing_qty > 0:
            realized = closing_qty * (price - prev_avg) * (1 if prev_qty > 0 else -1)
        new_qty = prev_qty + signed_qty
        state["qty"] = new_qty
        if new_qty == 0:
            state["avg"] = 0.0
            self._positions[key] = {"qty": 0.0, "avg": 0.0}
        elif (new_qty > 0 > prev_qty) or (new_qty < 0 < prev_qty):
            state["avg"] = price
            self._positions[key] = state
        else:
            state["avg"] = prev_avg
            self._positions[key] = state
        return realized


class ParamControllerBridge:
    """Handles fetching presets and reporting realized outcomes to the ParamController."""

    def __init__(
        self,
        base_url: str,
        refresh_interval: float = 45.0,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.refresh_interval = max(5.0, float(refresh_interval))
        self.timeout = timeout
        self._watches: dict[tuple[str, str], _WatchConfig] = {}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._cache_lock = Lock()
        self._task: asyncio.Task[Any] | None = None
        self._running = False
        self._feedback_tracker = ParamOutcomeTracker()
        self._feedback_wired = False

    def register_symbol(
        self,
        strategy: str,
        instrument: str,
        *,
        features: dict[str, float] | None = None,
    ) -> None:
        if not self.base_url:
            return
        key = (_norm_strategy(strategy), _norm_instrument(instrument))
        self._watches[key] = _WatchConfig(
            strategy=key[0],
            instrument=key[1],
            features=features or {"bias": 1.0},
        )

    def update_features(
        self,
        strategy: str,
        instrument: str,
        features: dict[str, float] | None,
    ) -> None:
        if not features:
            return
        key = (_norm_strategy(strategy), _norm_instrument(instrument))
        watch = self._watches.get(key)
        if not watch:
            return
        watch.features = {**watch.features, **{k: float(v) for k, v in features.items()}}

    def get_params(self, strategy: str, instrument: str) -> dict[str, Any] | None:
        key = (_norm_strategy(strategy), _norm_instrument(instrument))
        with self._cache_lock:
            return self._cache.get(key)

    async def start(self) -> None:
        if self._running or not self.base_url or not self._watches:
            return
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                _LOGGER.warning("Param bridge stop error: %s", exc, exc_info=True)
            finally:
                self._task = None

    async def _refresh_loop(self) -> None:
        while self._running:
            if not self._watches:
                await asyncio.sleep(self.refresh_interval)
                continue
            for key, watch in list(self._watches.items()):
                await self._refresh_watch(key, watch)
            await asyncio.sleep(self.refresh_interval)

    async def _refresh_watch(self, key: tuple[str, str], watch: _WatchConfig) -> None:
        url = f"{self.base_url}/param/{watch.strategy}/{watch.instrument}"
        params = _flatten_features(watch.features)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                _LOGGER.debug(
                    "Preset not found for %s/%s (will retry)",
                    watch.strategy,
                    watch.instrument,
                )
            else:
                _LOGGER.warning("Param fetch failed for %s: %s", url, exc, exc_info=True)
            return
        except httpx.HTTPError as exc:
            _LOGGER.warning("Param fetch error for %s: %s", url, exc)
            return

        cache_entry = {
            "config_id": payload.get("config_id"),
            "params": payload.get("params", {}),
            "policy_version": payload.get("policy_version"),
            "features": dict(watch.features),
            "strategy": watch.strategy,
            "instrument": watch.instrument,
            "preset_id": (payload.get("config_id") or "").split(":")[-1],
        }
        with self._cache_lock:
            self._cache[key] = cache_entry

    def wire_feedback(self, bus) -> None:
        if self._feedback_wired or not self.base_url:
            return

        async def _handler(event: dict[str, Any]) -> None:
            strategy = str(event.get("strategy_tag") or event.get("intent") or "strategy").split(
                ":"
            )[0]
            meta = event.get("strategy_meta") or {}
            preset_id = str(meta.get("preset_id") or meta.get("param_config_id", "")).split(":")[-1]
            instrument = meta.get("param_instrument") or event.get("symbol")
            if not preset_id or not instrument:
                return
            features = meta.get("param_features") or {}
            qty = float(event.get("filled_qty") or 0.0)
            price = float(event.get("avg_price") or 0.0)
            side = str(event.get("side") or "").upper()
            reward = self._feedback_tracker.process(
                _norm_strategy(meta.get("param_strategy") or strategy),
                _norm_instrument(instrument),
                preset_id,
                side,
                qty,
                price,
            )
            if reward == 0.0:
                return
            asyncio.create_task(
                self._send_outcome(
                    strategy=_norm_strategy(meta.get("param_strategy") or strategy),
                    instrument=_norm_instrument(instrument),
                    preset_id=preset_id,
                    reward=reward,
                    features=features,
                )
            )

        try:
            bus.subscribe("trade.fill", _handler)
            self._feedback_wired = True
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("Param bridge feedback wiring failed: %s", exc, exc_info=True)

    async def _send_outcome(
        self,
        *,
        strategy: str,
        instrument: str,
        preset_id: str,
        reward: float,
        features: dict[str, Any] | None = None,
    ) -> None:
        url = f"{self.base_url}/learn/outcome/{strategy}/{instrument}/{preset_id}"
        body = {"reward": reward, "features": features or {}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(url, json=body)
        except httpx.HTTPError as exc:
            _LOGGER.warning("Failed to post outcome to %s: %s", url, exc)


_PARAM_CLIENT: ParamControllerBridge | None = None


def bootstrap_param_client(
    base_url: str, refresh_interval: float = 45.0
) -> ParamControllerBridge | None:
    global _PARAM_CLIENT
    if not base_url:
        return None  # type: ignore[return-value]
    if _PARAM_CLIENT is None or _PARAM_CLIENT.base_url != base_url.rstrip("/"):
        _PARAM_CLIENT = ParamControllerBridge(base_url=base_url, refresh_interval=refresh_interval)
    return _PARAM_CLIENT


def get_param_client() -> ParamControllerBridge | None:
    return _PARAM_CLIENT


def get_cached_params(strategy: str, instrument: str) -> dict[str, Any] | None:
    client = get_param_client()
    if not client:
        return None
    return client.get_params(strategy, instrument)


def update_param_features(strategy: str, instrument: str, features: dict[str, float]) -> None:
    client = get_param_client()
    if not client:
        return
    client.update_features(strategy, instrument, features)


def update_context(strategy_name: str, symbol: str, features: dict[str, float]) -> None:
    """Standardized helper to report market context features to the ParamController."""
    update_param_features(strategy_name, symbol, features)


def apply_dynamic_config(strategy_instance: Any, symbol: str) -> None:
    """
    Universal helper to fetch and apply dynamic parameters to a strategy instance.

    Args:
        strategy_instance: The strategy object (must have .name or .cfg).
        symbol: The symbol to fetch params for.
    """
    try:
        # Determine strategy name
        strat_name = getattr(strategy_instance, "name", None)
        if not strat_name:
            strat_name = strategy_instance.__class__.__name__.replace("Strategy", "").lower()

        # Fetch params
        dyn = get_cached_params(strat_name, symbol)
        if not dyn:
            return

        params = dyn.get("params", {})
        if not params:
            return

        # Apply params
        # Priority 1: Update self._params (TrendStrategy pattern)
        if hasattr(strategy_instance, "_params") and hasattr(strategy_instance._params, "update"):
            strategy_instance._params.update(**params)
            return

        # Priority 2: Update self.cfg (Standard pattern)
        if hasattr(strategy_instance, "cfg"):
            cfg = strategy_instance.cfg
            updates = {}
            updated_keys = []

            for key, value in params.items():
                if hasattr(cfg, key):
                    # Type safe update if possible
                    current_val = getattr(cfg, key)
                    try:
                        # Cast to existing type
                        target_type = type(current_val)
                        if target_type == bool:
                            # Handle bool specially because bool("False") is True
                            if str(value).lower() in ("false", "0", "no", "off"):
                                new_val = False
                            else:
                                new_val = True
                        else:
                            new_val = target_type(value)

                        updates[key] = new_val
                        updated_keys.append(f"{key}={new_val}")
                    except (ValueError, TypeError):
                        pass

            if updates:
                from dataclasses import is_dataclass, replace

                if is_dataclass(cfg):
                    # Handle frozen dataclasses by replacing the object
                    try:
                        new_cfg = replace(cfg, **updates)
                        strategy_instance.cfg = new_cfg
                    except Exception:
                        # Fallback for non-frozen or other issues
                        for k, v in updates.items():
                            setattr(cfg, k, v)
                else:
                    # Standard object
                    for k, v in updates.items():
                        setattr(cfg, k, v)

                if hasattr(strategy_instance, "_log"):
                    strategy_instance._log.info(
                        f"[{strat_name.upper()}] Dynamic Config Applied: {', '.join(updated_keys)}"
                    )
                elif hasattr(strategy_instance, "log"):
                    strategy_instance.log.info(
                        f"[{strat_name.upper()}] Dynamic Config Applied: {', '.join(updated_keys)}"
                    )

    except Exception:
        pass  # Fail safe


__all__ = [
    "ParamControllerBridge",
    "ParamOutcomeTracker",
    "bootstrap_param_client",
    "get_param_client",
    "get_cached_params",
    "update_param_features",
    "update_context",
    "apply_dynamic_config",
]
