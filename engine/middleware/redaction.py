from __future__ import annotations

import os
import re
from typing import Iterable

from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REDACTION_KEYS = {"api_key", "secret", "token", "signature", "passphrase"}
SENSITIVE_VALUES = {
    value.strip()
    for value in (
        os.getenv("BINANCE_API_KEY"),
        os.getenv("BINANCE_API_SECRET"),
        os.getenv("OPS_API_TOKEN"),
    )
    if value
}

REDACTION_PATTERN = re.compile(
    r"(" + "|".join(re.escape(k) for k in REDACTION_KEYS) + r")\s*[=:]\s*([^\s,;]+)",
    re.IGNORECASE,
)


def _redact_text(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        key, value = match.group(1), match.group(2)
        if value in SENSITIVE_VALUES or len(value) > 4:
            return f"{key}=***redacted***"
        return match.group(0)

    redacted = REDACTION_PATTERN.sub(_replace, text)
    for secret in _iter_secrets():
        redacted = redacted.replace(secret, "***redacted***")
    return redacted


def _iter_secrets() -> Iterable[str]:
    for secret in SENSITIVE_VALUES:
        if secret:
            yield secret


class RedactionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.log_redactor = _redact_text
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
            redacted = _redact_text(body.decode("utf-8", errors="ignore"))
            response.body_iterator = iterate_in_threadpool(iter([redacted.encode("utf-8")]))
        return response
