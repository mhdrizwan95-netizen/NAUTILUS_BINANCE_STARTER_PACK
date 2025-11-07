from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request

_log = logging.getLogger("engine.ops_auth")
_TOKEN_FILE_WARNING_EMITTED = False


def load_ops_token() -> Optional[str]:
    """Return the configured Ops API token, preferring file-mounted secrets."""
    token = (os.getenv("OPS_API_TOKEN") or "").strip()
    token_file = os.getenv("OPS_API_TOKEN_FILE")
    if token_file:
        global _TOKEN_FILE_WARNING_EMITTED
        try:
            candidate = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            if not _TOKEN_FILE_WARNING_EMITTED:
                _log.warning("Failed to read OPS_API_TOKEN_FILE (%s): %s", token_file, exc)
                _TOKEN_FILE_WARNING_EMITTED = True
        else:
            if candidate:
                token = candidate
                _TOKEN_FILE_WARNING_EMITTED = False
    return token or None


def require_ops_token(request: Request) -> str:
    """Validate the inbound Ops control token, raising an HTTP error if missing."""
    expected = load_ops_token()
    if not expected:
        raise HTTPException(status_code=503, detail="OPS_API_TOKEN not configured on engine")
    provided = request.headers.get("X-Ops-Token") or request.headers.get("X-OPS-TOKEN")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Ops-Token")
    return expected
