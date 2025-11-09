"""Reusable FastAPI dependencies for Command Center control endpoints.

This helper consolidates token verification, two-man approval, and
idempotency enforcement so individual route handlers stay lean.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from fastapi import Header, HTTPException, Request, status

_TOKEN_LOCK = RLock()
_OPS_TOKEN_VALUE: str | None = None
_OPS_TOKEN_PATH: Path | None = None
_OPS_TOKEN_MTIME: float | None = None


class OpsTokenFileEmptyError(RuntimeError):
    """Raised when the OPS token file exists but contains no secret."""

    def __init__(self) -> None:
        super().__init__("OPS_API_TOKEN_FILE is empty")


class OpsTokenFileReadError(RuntimeError):
    """Raised when the OPS token file cannot be read."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Failed to read OPS_API_TOKEN_FILE: {path}")


class OpsTokenMissingError(RuntimeError):
    """Raised when no control token is configured."""

    def __init__(self) -> None:
        super().__init__(
            "OPS_API_TOKEN or OPS_API_TOKEN_FILE must be configured for control endpoints"
        )


def _load_ops_token() -> str:
    """Resolve the control token from env vars or mounted secret file, supporting rotation."""
    global _OPS_TOKEN_VALUE, _OPS_TOKEN_PATH, _OPS_TOKEN_MTIME  # noqa: PLW0603
    token_file = os.getenv("OPS_API_TOKEN_FILE")
    if token_file:
        path = Path(token_file)
        try:
            with _TOKEN_LOCK:
                mtime = path.stat().st_mtime
                if _OPS_TOKEN_PATH == path and _OPS_TOKEN_MTIME == mtime and _OPS_TOKEN_VALUE:
                    return _OPS_TOKEN_VALUE
                token = path.read_text(encoding="utf-8").strip()
                if not token:
                    raise OpsTokenFileEmptyError()
                _OPS_TOKEN_VALUE = token
                _OPS_TOKEN_PATH = path
                _OPS_TOKEN_MTIME = mtime
                return token
        except OSError as exc:  # pragma: no cover - defensive
            raise OpsTokenFileReadError(token_file) from exc

    token = os.getenv("OPS_API_TOKEN")
    if token:
        with _TOKEN_LOCK:
            _OPS_TOKEN_VALUE = token
            _OPS_TOKEN_PATH = None
            _OPS_TOKEN_MTIME = None
        return token
    with _TOKEN_LOCK:
        if _OPS_TOKEN_VALUE:
            return _OPS_TOKEN_VALUE
    raise OpsTokenMissingError()


def _load_approver_tokens() -> set[str]:
    """Return the configured secondary approval secrets, if any."""
    raw = os.getenv("OPS_APPROVER_TOKENS") or os.getenv("OPS_APPROVER_TOKEN", "")
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


@dataclass(frozen=True)
class ControlContext:
    """Metadata captured from request headers for downstream use."""

    actor: str | None
    approver: str | None
    idempotency_key: str | None


class ControlGuard:
    """FastAPI dependency enforcing token + optional two-man approval."""

    def __init__(self, *, require_idempotency: bool = False, require_two_man: bool = False) -> None:
        self.require_idempotency = require_idempotency
        self.require_two_man = require_two_man

    async def __call__(
        self,
        request: Request,
        x_ops_token: str | None = Header(None, alias="X-Ops-Token", convert_underscores=False),
        x_ops_actor: str | None = Header(None, alias="X-Ops-Actor", convert_underscores=False),
        x_ops_approver: str | None = Header(
            None, alias="X-Ops-Approver", convert_underscores=False
        ),
        idempotency_key: str | None = Header(
            None, alias="Idempotency-Key", convert_underscores=False
        ),
    ) -> ControlContext:
        expected_token = _load_ops_token()
        if x_ops_token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "auth.invalid_token",
                    "message": "Unauthorized control request",
                },
            )

        approver_token: str | None = None
        if self.require_two_man:
            allowed = _load_approver_tokens()
            if allowed:
                if not x_ops_approver or x_ops_approver not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={
                            "code": "auth.approver_required",
                            "message": "Secondary approver token required for this action",
                        },
                    )
                approver_token = x_ops_approver

        if self.require_idempotency:
            if not idempotency_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "idempotency.missing_header",
                        "message": "Missing Idempotency-Key header",
                    },
                )
        elif idempotency_key:
            # downstream handlers may still leverage the key when present
            pass

        return ControlContext(
            actor=x_ops_actor,
            approver=approver_token,
            idempotency_key=idempotency_key,
        )


# Convenience instances mirroring common guard profiles used across handlers.
IdempotentGuard = ControlGuard(require_idempotency=True, require_two_man=False)
IdempotentTwoManGuard = ControlGuard(require_idempotency=True, require_two_man=True)
TokenOnlyGuard = ControlGuard(require_idempotency=False, require_two_man=False)
