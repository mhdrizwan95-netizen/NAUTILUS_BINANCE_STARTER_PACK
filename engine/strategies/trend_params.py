from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

_SUPPRESSIBLE_EXCEPTIONS = (
    OSError,
    ValueError,
    json.JSONDecodeError,
)


@dataclass
class TrendParams:
    primary_fast: int
    primary_slow: int
    secondary_fast: int
    secondary_slow: int
    regime_fast: int
    regime_slow: int
    rsi_long_min: float
    rsi_long_max: float
    rsi_exit: float
    atr_stop_mult: float
    atr_target_mult: float
    cooldown_bars: int

    @classmethod
    def from_config(cls, cfg) -> TrendParams:
        return cls(
            primary_fast=cfg.primary.fast,
            primary_slow=cfg.primary.slow,
            secondary_fast=cfg.secondary.fast,
            secondary_slow=cfg.secondary.slow,
            regime_fast=cfg.regime.fast,
            regime_slow=cfg.regime.slow,
            rsi_long_min=cfg.rsi_long_min,
            rsi_long_max=cfg.rsi_long_max,
            rsi_exit=cfg.rsi_exit,
            atr_stop_mult=cfg.atr_stop_mult,
            atr_target_mult=cfg.atr_target_mult,
            cooldown_bars=cfg.cooldown_bars,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, type(getattr(self, key))(value))


class TrendAutoTuner:
    def __init__(self, cfg, params: TrendParams, *, logger: logging.Logger | None = None):
        self.cfg = cfg
        self.params = params
        self.enabled = bool(cfg.auto_tune_enabled)
        self.history: deque[dict] = deque(maxlen=max(10, int(cfg.auto_tune_history or 200)))
        self._trades_since_update = 0
        self._state_path = Path(cfg.auto_tune_state_path or "data/runtime/trend_auto_tune.json")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = logger or logging.getLogger("engine.trend.auto_tune")
        self._load_state()

    def observe_trade(
        self, symbol: str, pnl_pct: float, stop_bps: float, meta: dict | None = None
    ) -> None:
        record = {
            "symbol": symbol,
            "pnl_pct": pnl_pct,
            "stop_bps": stop_bps,
            "ts": time.time(),
        }
        if meta:
            record["meta"] = meta
        self.history.append(record)
        self._trades_since_update += 1
        self._persist_state()
        if self.enabled:
            self._maybe_tune()

    def _maybe_tune(self) -> None:
        if len(self.history) < self.cfg.auto_tune_min_trades:
            return
        if self._trades_since_update < self.cfg.auto_tune_interval:
            return
        window = list(self.history)[-self.cfg.auto_tune_min_trades :]
        wins = sum(1 for rec in window if rec.get("pnl_pct", 0.0) > 0.0)
        win_rate = wins / len(window) if window else 0.0
        changed = False
        if win_rate < self.cfg.auto_tune_win_low:
            changed |= self._adjust_for_losses()
        elif win_rate > self.cfg.auto_tune_win_high:
            changed |= self._adjust_for_wins()
        if changed:
            self._trades_since_update = 0
            self._log.info(
                "[TREND-AUTO] Updated parameters win_rate=%.2f params=%s",
                win_rate,
                self.params.to_dict(),
            )
            self._persist_state()

    def _adjust_for_losses(self) -> bool:
        changed = False
        stop = min(self.params.atr_stop_mult + 0.1, self.cfg.auto_tune_stop_max)
        target = min(self.params.atr_target_mult + 0.15, self.cfg.auto_tune_stop_max * 1.5)
        if stop != self.params.atr_stop_mult:
            self.params.atr_stop_mult = round(stop, 3)
            changed = True
        if target != self.params.atr_target_mult:
            self.params.atr_target_mult = round(target, 3)
            changed = True
        rsi_min = max(35.0, self.params.rsi_long_min - 1.0)
        rsi_max = min(85.0, self.params.rsi_long_max + 1.0)
        if rsi_min != self.params.rsi_long_min or rsi_max != self.params.rsi_long_max:
            self.params.rsi_long_min = rsi_min
            self.params.rsi_long_max = rsi_max
            changed = True
        self.params.cooldown_bars = min(6, self.params.cooldown_bars + 1)
        return changed

    def _adjust_for_wins(self) -> bool:
        changed = False
        stop = max(self.cfg.auto_tune_stop_min, self.params.atr_stop_mult - 0.1)
        target = max(self.params.atr_stop_mult + 0.3, self.params.atr_target_mult - 0.1)
        if stop != self.params.atr_stop_mult:
            self.params.atr_stop_mult = round(stop, 3)
            changed = True
        if target != self.params.atr_target_mult:
            self.params.atr_target_mult = round(target, 3)
            changed = True
        rsi_min = min(self.params.rsi_long_min + 1.0, self.params.rsi_long_max - 0.5)
        rsi_max = max(rsi_min + 5.0, self.params.rsi_long_max - 1.0)
        if rsi_min != self.params.rsi_long_min or rsi_max != self.params.rsi_long_max:
            self.params.rsi_long_min = rsi_min
            self.params.rsi_long_max = rsi_max
            changed = True
        self.params.cooldown_bars = max(1, self.params.cooldown_bars - 1)
        return changed

    def _persist_state(self) -> None:
        try:
            payload = {
                "params": self.params.to_dict(),
                "history": list(self.history)[-self.cfg.auto_tune_history :],
            }
            self._state_path.write_text(json.dumps(payload, indent=2))
        except _SUPPRESSIBLE_EXCEPTIONS:
            self._log.debug("[TREND-AUTO] Failed to persist tuner state", exc_info=True)

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
            for rec in data.get("history", []):
                self.history.append(rec)
            params = data.get("params")
            if params:
                self.params.update(**params)
            self._log.info(
                "[TREND-AUTO] Restored %d trades and params %s",
                len(self.history),
                self.params.to_dict(),
            )
        except _SUPPRESSIBLE_EXCEPTIONS:
            self._log.warning("[TREND-AUTO] Failed to restore tuner state", exc_info=True)
