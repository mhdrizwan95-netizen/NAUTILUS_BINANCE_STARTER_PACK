from __future__ import annotations

import os
from typing import Any, List, Optional

from .defaults import ALL_DEFAULTS


def _to_env_str(value: Any | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _get(key: str, default: Any | None = None) -> str:
    sentinel = default if default is not None else ALL_DEFAULTS.get(key)
    return os.environ.get(key, _to_env_str(sentinel))


def env_str(key: str, default: str | None = None) -> str:
    base_default = default if default is not None else ALL_DEFAULTS.get(key, "")
    return os.environ.get(key, _to_env_str(base_default))


def env_bool(key: str, default: bool) -> bool:
    raw = _get(key, default).strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def env_int(key: str, default: int) -> int:
    raw = _get(key, default).strip()
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return int(default)


def env_float(key: str, default: float) -> float:
    raw = _get(key, default).strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def env_csv(key: str, default_csv: str) -> List[str]:
    raw = _get(key, default_csv)
    if not raw:
        return []
    parts = [token.strip() for token in raw.split(",") if token.strip()]
    return parts


def split_symbols(value: str | None) -> Optional[List[str]]:
    """Parse a CSV list of symbols, supporting '*' for allow-all."""
    if not value:
        return None
    tokens = []
    for token in value.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        if cleaned == "*":
            return None
        base = cleaned.split(".")[0].upper()
        tokens.append(base)
    if not tokens:
        return None
    return sorted(set(tokens))


__all__ = [
    "env_bool",
    "env_csv",
    "env_float",
    "env_int",
    "env_str",
    "split_symbols",
]
