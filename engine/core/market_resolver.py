from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict


def _parse_inline_map(raw: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for token in raw.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        key, value = token.split(":", 1)
        key = key.strip().upper()
        value = value.strip().lower()
        if key:
            mapping[key] = value
    return mapping


def _load_file_map(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {}
    text = text.strip()
    if not text:
        return {}
    # Try JSON first
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k).upper(): str(v).lower() for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    # Fallback: simple KEY:VALUE per line
    mapping: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        mapping[key.strip().upper()] = value.strip().lower()
    return mapping


@lru_cache(maxsize=1)
def _market_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    inline = os.getenv("MARKET_ROUTE_MAP", "")
    if inline:
        mapping.update(_parse_inline_map(inline))
    file_path = os.getenv("MARKET_ROUTE_MAP_FILE", "").strip()
    if file_path:
        mapping.update(_load_file_map(file_path))
    return mapping


def resolve_market(symbol: str, default: str | None) -> str | None:
    """
    Resolve the preferred market ('spot', 'margin', 'futures', 'options', etc.)
    for a given symbol based on configuration.
    """
    mapping = _market_map()
    if not mapping:
        return default
    if not symbol:
        return default
    base = symbol.split(".")[0].upper()
    qualified = symbol.upper()
    if qualified in mapping:
        return mapping[qualified]
    if base in mapping:
        return mapping[base]
    if "*" in mapping:
        return mapping["*"]
    return default
