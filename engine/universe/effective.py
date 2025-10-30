from __future__ import annotations

import os
from typing import List, Optional

from engine.config.defaults import GLOBAL_DEFAULTS
from engine.config.env import _get, split_symbols

try:  # Optional import when the scanner package is not available in minimal envs
    from engine.strategies.symbol_scanner import SymbolScanner  # type: ignore
except Exception:  # pragma: no cover - scanner is optional
    SymbolScanner = None  # type: ignore


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
        return split_symbols(raw)


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
