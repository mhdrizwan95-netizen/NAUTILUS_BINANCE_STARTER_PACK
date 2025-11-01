from __future__ import annotations

"""
Persistence for DEX sniper intent and position state.

Positions are stored in a simple JSON file so restarts do not forget
open trades.  This is intentionally lightweight; a future rev can swap
in SQLite without touching the surrounding strategy.
"""

from dataclasses import dataclass, asdict, field
import json
import os
import time
import uuid
from typing import Dict, Iterable, List, Optional


@dataclass(slots=True)
class DexTarget:
    pct: float
    portion: float
    filled: bool = False
    filled_at: float | None = None


@dataclass(slots=True)
class DexPosition:
    pos_id: str
    symbol: str
    chain: str
    address: str
    tier: str
    qty: float
    entry_price: float
    notional: float
    stop_loss_pct: float
    trail_pct: float
    opened_at: float
    status: str = "open"
    metadata: Dict[str, float] = field(default_factory=dict)
    tp_targets: List[DexTarget] = field(default_factory=list)
    closed_at: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["tp_targets"] = [asdict(t) for t in self.tp_targets]
        return data

    @classmethod
    def from_dict(cls, payload: dict) -> "DexPosition":
        targets = [
            DexTarget(**item)
            for item in payload.get("tp_targets", [])
            if isinstance(item, dict)
        ]
        return cls(
            pos_id=str(payload.get("pos_id") or payload.get("id") or uuid.uuid4().hex),
            symbol=str(payload.get("symbol", "")),
            chain=str(payload.get("chain", "")),
            address=str(payload.get("address", "")),
            tier=str(payload.get("tier", "")),
            qty=float(payload.get("qty", 0.0) or 0.0),
            entry_price=float(payload.get("entry_price", 0.0) or 0.0),
            notional=float(payload.get("notional", 0.0) or 0.0),
            stop_loss_pct=float(payload.get("stop_loss_pct", 0.0) or 0.0),
            trail_pct=float(payload.get("trail_pct", 0.0) or 0.0),
            opened_at=float(payload.get("opened_at") or time.time()),
            status=str(payload.get("status", "open")),
            metadata=dict(payload.get("metadata") or {}),
            tp_targets=targets,
            closed_at=payload.get("closed_at"),
        )


class DexState:
    def __init__(self, path: str) -> None:
        self.path = path
        self._positions: Dict[str, DexPosition] = {}
        self._symbol_index: Dict[str, str] = {}
        self._load()

    # Persistence -----------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
        except FileNotFoundError:
            raw = {}
        except Exception:
            raw = {}

        if isinstance(raw, dict):
            positions = raw.get("positions") or raw
        else:
            positions = {}

        for pos_id, blob in positions.items():
            if not isinstance(blob, dict):
                continue
            pos = DexPosition.from_dict({"pos_id": pos_id, **blob})
            self._positions[pos.pos_id] = pos
            if pos.status == "open":
                self._symbol_index[pos.symbol.upper()] = pos.pos_id

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            payload = {
                "positions": {
                    pid: pos.to_dict() for pid, pos in self._positions.items()
                }
            }
            tmp_path = f"{self.path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"), sort_keys=True)
            os.replace(tmp_path, self.path)
        except Exception:
            # Persistence is best-effort; ignore failures.
            pass

    # State helpers ----------------------------------------------------------------
    def positions(self) -> Iterable[DexPosition]:
        return list(self._positions.values())

    def open_positions(self) -> List[DexPosition]:
        return [pos for pos in self._positions.values() if pos.status == "open"]

    def count_open(self) -> int:
        return sum(1 for pos in self._positions.values() if pos.status == "open")

    def has_open(self, symbol: str) -> bool:
        return symbol.upper() in self._symbol_index

    def get_open(self, symbol: str) -> Optional[DexPosition]:
        pos_id = self._symbol_index.get(symbol.upper())
        if pos_id is None:
            return None
        return self._positions.get(pos_id)

    def open_position(
        self,
        *,
        symbol: str,
        chain: str,
        address: str,
        tier: str,
        qty: float,
        entry_price: float,
        notional: float,
        stop_loss_pct: float,
        trail_pct: float,
        metadata: Optional[dict] = None,
        targets: Optional[Iterable[tuple[float, float]]] = None,
    ) -> DexPosition:
        pos_id = uuid.uuid4().hex
        tp_targets = [
            DexTarget(pct=float(pct), portion=float(portion))
            for pct, portion in (targets or [])
        ]
        position = DexPosition(
            pos_id=pos_id,
            symbol=symbol.upper(),
            chain=chain.upper(),
            address=address,
            tier=tier.upper(),
            qty=float(qty),
            entry_price=float(entry_price),
            notional=float(notional),
            stop_loss_pct=float(stop_loss_pct),
            trail_pct=float(trail_pct),
            opened_at=time.time(),
            metadata=dict(metadata or {}),
            tp_targets=tp_targets,
        )
        self._positions[pos_id] = position
        self._symbol_index[position.symbol] = pos_id
        self._save()
        return position

    def close_position(
        self, pos_id: str, *, reason: str | None = None
    ) -> Optional[DexPosition]:
        position = self._positions.get(pos_id)
        if position is None:
            return None
        position.status = "closed"
        position.closed_at = time.time()
        self._symbol_index.pop(position.symbol, None)
        if reason:
            position.metadata["closed_reason"] = reason
        position.metadata["last_action"] = reason or "closed"
        self._save()
        return position

    def record_target_fill(self, pos_id: str, index: int) -> None:
        position = self._positions.get(pos_id)
        if position is None:
            return
        if 0 <= index < len(position.tp_targets):
            target = position.tp_targets[index]
            target.filled = True
            target.filled_at = time.time()
            self._save()

    def set_metadata(self, pos_id: str, key: str, value) -> None:
        position = self._positions.get(pos_id)
        if position is None:
            return
        position.metadata[key] = value
        self._save()

    def register_fill(
        self,
        pos_id: str,
        qty_sold: float,
        *,
        target_index: int | None = None,
        reason: str | None = None,
    ) -> Optional[DexPosition]:
        position = self._positions.get(pos_id)
        if position is None:
            return None
        qty_sold = float(max(qty_sold, 0.0))
        if qty_sold <= 0:
            return position
        position.qty = max(0.0, float(position.qty) - qty_sold)
        if position.qty <= 0:
            position.status = "closed"
            position.closed_at = time.time()
            self._symbol_index.pop(position.symbol, None)
        if target_index is not None and 0 <= target_index < len(position.tp_targets):
            target = position.tp_targets[target_index]
            target.filled = True
            target.filled_at = time.time()
        if reason:
            position.metadata["last_action"] = reason
        self._save()
        return position

    def refresh_position(self, pos_id: str) -> Optional[DexPosition]:
        return self._positions.get(pos_id)
