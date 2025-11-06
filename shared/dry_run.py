from __future__ import annotations

import logging
import os
from typing import Iterable, Set

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def dry_run_enabled() -> bool:
    return os.getenv("DRY_RUN", "0").lower() in {"1", "true", "yes"}


def install_dry_run_guard(app: FastAPI, allow_paths: Iterable[str] | None = None) -> None:
    whitelisted: Set[str] = {"/health", "/metrics"}
    if allow_paths:
        whitelisted.update(allow_paths)

    class DryRunGuardMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if (
                dry_run_enabled()
                and request.method.upper() in _MUTATING_METHODS
                and request.url.path not in whitelisted
            ):
                return JSONResponse(
                    status_code=HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "error": {
                            "code": "dry_run.enabled",
                            "message": "Mutating operations are disabled while DRY_RUN=1.",
                        }
                    },
                )
            return await call_next(request)

    app.add_middleware(DryRunGuardMiddleware)


def log_dry_run_banner(component: str) -> None:
    if dry_run_enabled():
        logging.getLogger(component).warning("DRY_RUN=1 — external side-effects are disabled.")
