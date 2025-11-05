"""Reusable FastAPI dependencies for Command Center control endpoints.

This helper consolidates token verification, two-man approval, and
idempotency enforcement so individual route handlers stay lean.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Optional, Set

from fastapi import Header, HTTPException, Request, status

_TOKEN_LOCK = RLock()
_OPS_TOKEN: Optional[str] = None
_APPROVER_TOKENS: Optional[Set[str]] = None


def _load_ops_token() -> str:
    """Resolve the control token from env vars or mounted secret file."""
    global _OPS_TOKEN  # noqa: PLW0603
    with _TOKEN_LOCK:
        if _OPS_TOKEN is not None:
            return _OPS_TOKEN
        token = os.getenv("OPS_API_TOKEN")
        token_file = os.getenv("OPS_API_TOKEN_FILE")
        if token_file:
            try:
                token = Path(token_file).read_text(encoding="utf-8").strip()
            except OSError as exc:  # pragma: no cover - defensive
                raise RuntimeError(
                    f"Failed to read OPS_API_TOKEN_FILE: {token_file}"
                ) from exc
        if not token:
            raise RuntimeError(
                "OPS_API_TOKEN or OPS_API_TOKEN_FILE must be configured for control endpoints"
            )
        _OPS_TOKEN = token
        return token


def _load_approver_tokens() -> Set[str]:
    """Return the configured secondary approval secrets, if any."""
    global _APPROVER_TOKENS  # noqa: PLW0603
    with _TOKEN_LOCK:
        if _APPROVER_TOKENS is not None:
            return _APPROVER_TOKENS
        raw = os.getenv("OPS_APPROVER_TOKENS") or os.getenv("OPS_APPROVER_TOKEN", "")
        if not raw:
            _APPROVER_TOKENS = set()
        else:
            _APPROVER_TOKENS = {item.strip() for item in raw.split(",") if item.strip()}
        return _APPROVER_TOKENS


@dataclass(frozen=True)
class ControlContext:
    """Metadata captured from request headers for downstream use."""

    actor: Optional[str]
    approver: Optional[str]
    idempotency_key: Optional[str]


class ControlGuard:
    """FastAPI dependency enforcing token + optional two-man approval."""

    def __init__(self, *, require_idempotency: bool = False, require_two_man: bool = False) -> None:
        self.require_idempotency = require_idempotency
        self.require_two_man = require_two_man

    async def __call__(
        self,
        request: Request,
        x_ops_token: Optional[str] = Header(None, convert_underscores=False),
        x_ops_actor: Optional[str] = Header(None, convert_underscores=False),
        x_ops_approver: Optional[str] = Header(None, convert_underscores=False),
        idempotency_key: Optional[str] = Header(
            None, alias="Idempotency-Key", convert_underscores=False
        ),
    ) -> ControlContext:
        expected_token = _load_ops_token()
        if x_ops_token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized control request",
            )

        approver_token: Optional[str] = None
        if self.require_two_man:
            allowed = _load_approver_tokens()
            if allowed:
                if not x_ops_approver or x_ops_approver not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Approver token required",
                    )
                approver_token = x_ops_approver

        if self.require_idempotency:
            if not idempotency_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing Idempotency-Key header",
                )
        else:
            if idempotency_key:
                # downstream handlers may still leverage the key when present
                pass

        return ControlContext(
            actor=x_ops_actor,
            approver=approver_token,
            idempotency_key=idempotency_key,
        )


# Convenience instances mirroring common guard profiles used across handlers.
IdempotentTwoManGuard = ControlGuard(require_idempotency=True, require_two_man=True)
TokenOnlyGuard = ControlGuard(require_idempotency=False, require_two_man=False)
