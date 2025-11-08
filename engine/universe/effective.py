from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml

from engine.config.defaults import GLOBAL_DEFAULTS
from engine.config.env import _get, split_symbols

try:  # Optional import when the scanner package is not available in minimal envs
    from engine.strategies.symbol_scanner import SymbolScanner  # type: ignore
except Exception:  # pragma: no cover - scanner is optional
    SymbolScanner = None  # type: ignore


_RUNTIME_PATH = Path("config/runtime.yaml")


def _load_runtime_core() -> List[str]:
    try:
        raw = yaml.safe_load(_RUNTIME_PATH.read_text()) if _RUNTIME_PATH.exists() else None
    except Exception:
        return []
    symbols = (raw or {}).get("symbols", {})
    core = symbols.get("core") if isinstance(symbols, dict) else None
    if not isinstance(core, list):
        return []
    cleaned = [token.split(".")[0].upper() for token in core if token]
    return sorted({token for token in cleaned if token and token != "*"})  # nosec B105


def _scanner_enabled() -> bool:
    raw = os.environ.get("SYMBOL_SCANNER_ENABLED")
    if raw is None:
        raw = str(GLOBAL_DEFAULTS.get("SYMBOL_SCANNER_ENABLED", "false"))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class StrategyUniverse:
    """Resolves the effective trading universe for a strategy."""

    def __init__(self, scanner: SymbolScanner | None) -> None:
        self._scanner = scanner

    def get(self, strategy_name: str) -> Optional[List[str]]:
        """Return the effective symbol universe for *strategy_name*.

        If the dynamic symbol scanner is enabled and provided, its selection is used.
        Otherwise the global ``TRADE_SYMBOLS`` allow-list acts as the backstop. When
        ``TRADE_SYMBOLS`` is ``*`` or empty the method returns ``None`` meaning
        "allow all".
        """

        if _scanner_enabled() and self._scanner:
            try:
                selected = self._scanner.current_universe(strategy=strategy_name)
            except AttributeError:  # Legacy scanners only expose ``get_selected``
                selected = self._scanner.get_selected()  # type: ignore[assignment]
            symbols = _normalise_symbols(selected)
            return symbols if symbols else None

        raw = _get("TRADE_SYMBOLS", GLOBAL_DEFAULTS["TRADE_SYMBOLS"])
        explicit_allow_all = bool(raw and raw.strip() == "*")
        parsed = split_symbols(raw)
        if parsed:
            return parsed
        if explicit_allow_all:
            return None
        runtime_core = _load_runtime_core()
        return runtime_core or None


def _normalise_symbols(symbols: Optional[List[str]]) -> List[str]:
    if not symbols:
        return []
    normalised: List[str] = []
    for token in symbols:
        if not token:
            continue
        base = token.split(".")[0].upper()
        if base == "*":
            return []
        normalised.append(base)
    return sorted(set(normalised))


__all__ = ["StrategyUniverse"]
