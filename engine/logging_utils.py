from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import os
from typing import Any, Dict, Optional


_REQUEST_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)

_SERVICE_NAME = os.getenv("OBS_SERVICE_NAME", "engine")
_SENSITIVE_ENV_VARS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPS_API_TOKEN",
    "OPS_APPROVER_TOKENS",
]


def _load_sensitive_values() -> set[str]:
    values: set[str] = set()
    for name in _SENSITIVE_ENV_VARS:
        value = (os.getenv(name) or "").strip()
        if value:
            values.add(value)
    return values


class JsonFormatter(logging.Formatter):
    redaction_keys = {"api_key", "secret", "token", "signature", "passphrase"}

    def __init__(self) -> None:
        super().__init__()
        self._sensitive_values = _load_sensitive_values()

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "ts": dt.datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "service": _SERVICE_NAME,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = _REQUEST_ID.get()
        if request_id:
            payload["correlation_id"] = request_id
        if hasattr(record, "event"):
            payload["event"] = getattr(record, "event")
        if record.exc_info:
            payload["stack"] = self.formatException(record.exc_info)
        return json.dumps(self._redact(payload), default=str)

    def _redact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        scrubbed: Dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                lowered = key.lower()
                if lowered in self.redaction_keys or any(
                    secret and secret in value for secret in self._sensitive_values
                ):
                    scrubbed[key] = "***redacted***"
                    continue
            scrubbed[key] = value
        return scrubbed


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def bind_request_id(request_id: str) -> contextvars.Token[Optional[str]]:
    return _REQUEST_ID.set(request_id)


def reset_request_context(token: contextvars.Token[Optional[str]]) -> None:
    try:
        _REQUEST_ID.reset(token)
    except LookupError:
        pass
