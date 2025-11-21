import asyncio
import contextvars
import glob
import json
import logging
import os
import re
import shlex
import subprocess
import time
import uuid
from contextlib import suppress
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from pathlib import Path as Path2
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.websockets import WebSocketDisconnect

from shared.dry_run import install_dry_run_guard, log_dry_run_banner

os.environ.setdefault("OBS_SERVICE_NAME", "ops-api")

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ModuleNotFoundError:  # pragma: no cover - optional in minimal envs
    FastAPIInstrumentor = None  # type: ignore[assignment]

from engine.logging_utils import bind_request_id, reset_request_context, setup_logging
from engine.metrics import observe_http_request
from engine.middleware.redaction import RedactionMiddleware
from ops import ui_state
from ops.background import account_broadcaster, default_symbols, price_stream
from ops.env import engine_endpoints
from ops.pnl_collector import PNL_REALIZED, PNL_UNREALIZED
from ops.pnl_dashboard import router as pnl_router
from ops.portfolio_collector import (
    PORTFOLIO_CASH,
    PORTFOLIO_EQUITY,
    PORTFOLIO_GAIN,
    PORTFOLIO_LAST,
    PORTFOLIO_PREV,
    PORTFOLIO_RET,
)
from ops.prometheus import get_or_create_counter, render_latest
from ops.routes.orders import router as orders_router
from ops.situations.router import router as situations_router
from ops.strategy_router import router as strategy_router
from ops.telemetry_store import (
    Metrics as _Metrics,
)
from ops.telemetry_store import (
    Snapshot as _Snapshot,
)
from ops.telemetry_store import (
    load as _load_snap,
)
from ops.telemetry_store import (
    save as _save_snap,
)
from ops.ui_api import (
    FlattenReasonRequired,
    KillSwitchReasonRequired,
    broadcast_account,
    cc_health,
    ws_account,
    ws_events,
    ws_orders,
    ws_price,
    ws_trades,
)
from ops.ui_api import router as ui_router
from ops.ui_services import (
    ConfigService,
    FeedsGovernanceService,
    OpsGovernanceService,
    OrdersService,
    PortfolioService,
    RiskGuardService,
    ScannerService,
    StrategyGovernanceService,
)
from shared.time_guard import check_clock_skew

try:  # pragma: no cover - optional test dependency
    from respx.models import SideEffectError as _RespxSideEffectError
except ImportError:  # pragma: no cover - prod deployments lack respx
    _RESPX_ERRORS: tuple[type[Exception], ...] = ()
else:
    _RESPX_ERRORS = (_RespxSideEffectError,)

_ENGINE_HEALTH_ERRORS = (httpx.HTTPError, asyncio.TimeoutError, ValueError)
_HTTP_CLIENT_ERRORS = (httpx.HTTPError, ValueError) + _RESPX_ERRORS

# Risk monitoring configuration
RISK_LIMIT_USD = float(os.getenv("RISK_LIMIT_USD_PER_SYMBOL", "1000"))
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL")
EXPOSURE_CHECK_INTERVAL = int(os.getenv("EXPOSURE_CHECK_INTERVAL_SEC", "30"))

# Do not resolve endpoints at import time; tests mutate env per case.


class MetricsIn(BaseModel):
    pnl_realized: float | None = None
    pnl_unrealized: float | None = None
    drift_score: float | None = None
    policy_confidence: float | None = None
    order_fill_ratio: float | None = None
    venue_latency_ms: float | None = None
    # NEW: account metrics
    account_equity_usd: float | None = None
    cash_usd: float | None = None
    gross_exposure_usd: float | None = None


setup_logging()

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "v1"
SUPPORTED_API_VERSIONS = {"v1"}
API_VERSION_PATTERN = re.compile(r"^v\d+$")


APP = FastAPI(title="Ops API")
install_dry_run_guard(APP, allow_paths={"/health", "/metrics", "/metrics/prometheus", "/static"})
log_dry_run_banner("ops.api")


@APP.get("/metrics", include_in_schema=False)
def _metrics():
    payload, content_type = render_latest()
    return Response(payload, media_type=content_type)


if FastAPIInstrumentor:
    FastAPIInstrumentor.instrument_app(APP)
_REQ_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("REQ_ID", default=None)
_API_VERSION: contextvars.ContextVar[str] = contextvars.ContextVar(
    "API_VERSION", default=DEFAULT_API_VERSION
)


def current_request_id() -> str | None:
    return _REQ_ID.get()


def _structured_error_payload(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    req_id = current_request_id()
    if req_id:
        payload["error"]["requestId"] = req_id
    return payload


def _structured_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = _structured_error_payload(code, message, details=details)
    return JSONResponse(payload, status_code=status_code)


class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        _REQ_ID.set(req_id)
        token = bind_request_id(req_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_context(token)
        response.headers["X-Request-ID"] = req_id
        return response


class _ApiVersionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        requested = request.headers.get("X-API-Version")
        version = DEFAULT_API_VERSION
        if requested:
            requested = requested.strip()
            if not API_VERSION_PATTERN.fullmatch(requested):
                return _structured_error_response(
                    status.HTTP_400_BAD_REQUEST,
                    "api.invalid_version",
                    "X-API-Version must match pattern v<number> (e.g. v1).",
                    {"provided": requested},
                )
            if requested not in SUPPORTED_API_VERSIONS:
                return _structured_error_response(
                    status.HTTP_406_NOT_ACCEPTABLE,
                    "api.unsupported_version",
                    "Requested API version is not supported.",
                    {
                        "requested": requested,
                        "supported": sorted(SUPPORTED_API_VERSIONS),
                    },
                )
            version = requested

        token = _API_VERSION.set(version)
        try:
            response = await call_next(request)
        finally:
            _API_VERSION.reset(token)

        response.headers["X-API-Version"] = version
        response.headers["X-API-Versions"] = ",".join(sorted(SUPPORTED_API_VERSIONS))
        return response


class _HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        route = _route_template(request)
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration = time.perf_counter() - start
            status_code = response.status_code if response else 500
            observe_http_request("ops-api", request.method, route, status_code, duration)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route and getattr(route, "path", None):
        return route.path
    return request.url.path


APP.add_middleware(_RequestIDMiddleware)
APP.add_middleware(_ApiVersionMiddleware)
APP.add_middleware(_HttpMetricsMiddleware)
APP.add_middleware(RedactionMiddleware)
APP.include_router(orders_router)
APP.include_router(strategy_router)
APP.include_router(pnl_router)
APP.include_router(situations_router)
APP.include_router(ui_router)


@APP.exception_handler(HTTPException)
async def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    code = f"http.{exc.status_code}"
    message = HTTPStatus(exc.status_code).phrase
    details: dict[str, Any] | None = None
    if isinstance(detail, dict):
        code = detail.get("code", code)
        message = str(detail.get("message", message))
        details = detail.get("details")
    elif isinstance(detail, str):
        message = detail
    return _structured_error_response(exc.status_code, code, message, details)


def _sanitize_ctx_value(value: Any) -> Any:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {k: _sanitize_ctx_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        sanitized = [_sanitize_ctx_value(item) for item in value]
        return sanitized if isinstance(value, list) else list(sanitized)
    if hasattr(value, "__dict__"):
        return str(value)
    return value


def _sanitize_validation_errors(
    errors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    sanitized: list[dict[str, Any]] = []
    reason_hint: str | None = None
    for err in errors:
        data = dict(err)
        original_ctx = err.get("ctx")
        if isinstance(original_ctx, dict):
            err_obj = original_ctx.get("error")
            data["ctx"] = {k: _sanitize_ctx_value(v) for k, v in original_ctx.items()}
            if isinstance(err_obj, FlattenReasonRequired):
                reason_hint = "flatten"
            elif isinstance(err_obj, KillSwitchReasonRequired):
                reason_hint = "kill"
        sanitized.append(data)
    return sanitized, reason_hint


@APP.exception_handler(RequestValidationError)
async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors, reason_hint = _sanitize_validation_errors(exc.errors())
    if reason_hint == "flatten":
        return _structured_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "reason.required",
            "A reason is required when issuing flatten requests.",
        )
    if reason_hint == "kill":
        return _structured_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "reason.required",
            "Provide an audit reason when disabling trading.",
        )
    return _structured_error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "request.validation_failed",
        "Request validation failed.",
        {"fields": errors},
    )


@APP.exception_handler(Exception)
async def _handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception during request processing", exc_info=exc)
    return _structured_error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal.server_error",
        "An internal server error occurred.",
    )


@APP.exception_handler(FlattenReasonRequired)
async def _handle_flatten_reason_error(
    request: Request, exc: FlattenReasonRequired
) -> JSONResponse:
    return _structured_error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "reason.required",
        "A reason is required when issuing flatten requests.",
    )


@APP.exception_handler(KillSwitchReasonRequired)
async def _handle_kill_switch_reason_error(
    request: Request, exc: KillSwitchReasonRequired
) -> JSONResponse:
    return _structured_error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "reason.required",
        "Provide an audit reason when disabling trading.",
    )


@APP.on_event("startup")
async def _ops_clock_skew_probe() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: check_clock_skew("ops"))


@APP.get("/readyz")
async def readyz():
    try:
        eng = await engine_health()
    except httpx.HTTPError:
        return {"ok": False}
    else:
        return {"ok": eng.get("engine") == "ok"}


# T6: Auth token for control actions
class OpsApiTokenFileError(RuntimeError):
    """Raised when the Ops API token file cannot be read."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Failed to read OPS_API_TOKEN_FILE ({path})")


class OpsApiTokenMissingError(RuntimeError):
    """Raised when Ops API token configuration is missing."""

    def __init__(self) -> None:
        super().__init__("Set OPS_API_TOKEN or OPS_API_TOKEN_FILE before starting the Ops API")


def _load_ops_token() -> str:
    token = os.getenv("OPS_API_TOKEN")
    token_file = os.getenv("OPS_API_TOKEN_FILE")
    if token_file:
        try:
            secret = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OpsApiTokenFileError(token_file) from exc
        if secret:
            token = secret
    dry_run = os.getenv("DRY_RUN", "0").lower() in {"1", "true", "yes"}
    if dry_run and not token:
        return "dry-run-token"
    if not token or token == "dev-token":
        raise OpsApiTokenMissingError()
    return token


@lru_cache(maxsize=1)
def get_expected_token() -> str:
    """Return the memoized control token for Ops API actions."""
    return _load_ops_token()


def reset_expected_token_cache() -> None:
    """Allow tests to clear the cached token when env vars change."""
    get_expected_token.cache_clear()


def _check_auth(request):
    """Check X-OPS-TOKEN header for control actions."""
    auth_header = request.headers.get("X-OPS-TOKEN")
    expected = get_expected_token()
    if not auth_header or auth_header != expected:
        raise HTTPException(401, "Invalid or missing X-OPS-TOKEN")


@APP.get("/metrics_snapshot")
def get_metrics_snapshot():
    s = _load_snap()
    return {"metrics": s.metrics.__dict__, "ts": s.ts}


@APP.post("/metrics_snapshot")
def post_metrics_snapshot(m: MetricsIn):
    s = _load_snap()
    d = s.metrics.__dict__.copy()
    # apply partial updates
    for k, v in m.dict(exclude_unset=True).items():
        if v is not None:
            d[k] = float(v)
    new = _Snapshot(metrics=_Metrics(**d), ts=time.time())
    _save_snap(new)
    return {"ok": True, "ts": new.ts}


# ---------------------------------------------------------------------------

# Enable CORS for React frontend integration
APP.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",  # Vite dev
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_FILE = Path(__file__).resolve().parent / "state.json"
ML_URL = os.getenv("HMM_URL", "http://127.0.0.1:8010")


# --- network helpers (timeouts/retries) --------------------------------------
def _http_retry_get(url: str, *, timeout: float = 1.0, attempts: int = 3, backoff: float = 0.2):
    for i in range(max(1, attempts)):
        try:
            headers = {}
            rid = _REQ_ID.get()
            if rid:
                headers["X-Request-ID"] = rid
            r = httpx.get(url, timeout=timeout, headers=headers or None)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            if i == attempts - 1:
                break
            time.sleep(backoff * (i + 1))
    return {}


def _http_retry_post(
    url: str,
    *,
    json: dict,
    timeout: float = 5.0,
    attempts: int = 3,
    backoff: float = 0.2,
):
    for i in range(max(1, attempts)):
        try:
            headers = {}
            rid = _REQ_ID.get()
            if rid:
                headers["X-Request-ID"] = rid
            r = httpx.post(url, json=json, timeout=timeout, headers=headers or None)
            r.raise_for_status()
        except httpx.HTTPError:
            if i == attempts - 1:
                raise
            time.sleep(backoff * (i + 1))
        else:
            return r


class KillReq(BaseModel):
    enabled: bool


class RetrainReq(BaseModel):
    feature_sequences: list
    labels: list[int] | None = None


@APP.get("/status")
async def get_status():
    st = {"ts": int(time.time()), "trading_enabled": True}
    if STATE_FILE.exists():
        with suppress(json.JSONDecodeError, OSError):
            st.update(json.loads(STATE_FILE.read_text()))

    # Extend with richer runtime info for the dash
    try:
        macro_state = int(os.environ.get("MACRO_STATE", "1"))
        st["macro_state"] = macro_state
        lineage_path = os.path.join("data", "memory_vault", "lineage_index.json")
        if os.path.exists(lineage_path):
            with open(lineage_path) as f:
                j = json.load(f)
            st["lineage_total_generations"] = len(j.get("models", []))
            st["lineage_latest"] = j["models"][-1] if j.get("models") else {}
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        st["status_warning"] = str(exc)

    # include latest account snapshot
    st["balances"] = ACCOUNT_CACHE.get("balances", {})
    st["pnl"] = ACCOUNT_CACHE.get("pnl", {})
    st["positions"] = ACCOUNT_CACHE.get("positions", [])
    st["equity"] = ACCOUNT_CACHE.get("equity", 0.0)
    st["cash"] = ACCOUNT_CACHE.get("cash", 0.0)
    st["exposure"] = ACCOUNT_CACHE.get("exposure", 0.0)

    st["ml"] = _http_retry_get(f"{ML_URL}/health", timeout=0.5, attempts=2, backoff=0.1) or {
        "ok": False
    }

    try:
        engine = await engine_health()
    except _ENGINE_HEALTH_ERRORS as exc:
        engine = {"ok": False, "error": str(exc)}
    st["engine"] = engine

    return {"ok": True, "state": st}


@APP.post("/kill")
def kill(req: KillReq, request: Request):
    _check_auth(request)
    state = {"trading_enabled": bool(req.enabled)}
    STATE_FILE.write_text(json.dumps(state))
    return {"ok": True, "state": state}


@APP.post("/retrain")
def retrain(req: RetrainReq, request: Request):
    _check_auth(request)
    # proxy to ML service
    try:
        r = _http_retry_post(
            f"{ML_URL}/train",
            json={
                "symbol": "BTCUSDT",
                "feature_sequences": req.feature_sequences,
                "labels": req.labels or [],
            },
            timeout=10.0,
            attempts=2,
            backoff=0.2,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(500, f"ML retrain failed: {exc}") from exc
    else:
        return {"ok": True, "ml_response": r.json()}


# ---------- New: mode metadata for dashboard ----------
@APP.get("/meta")
def meta():
    """Return metadata including trading mode."""
    from adapters.account_provider import BinanceAccountProvider

    mode = os.getenv("BINANCE_MODE", "live")
    exchanges = []
    provider = BinanceAccountProvider()
    if provider.spot_base != "":
        exchanges.append("SPOT")
    if provider.usdm_base != "":
        exchanges.append("USDM")
    if provider.coinm_base != "":
        exchanges.append("COIN-M")
    return {"ok": True, "mode": mode, "exchanges": exchanges}


# ---------- New: artifacts + lineage ----------
@APP.get("/artifacts/m15")
def list_artifacts_m15():
    """Return calibration PNGs for gallery (reward_heatmap, policy_boundary, rolling_winrate)."""
    base = os.path.join("data", "processed", "calibration")
    files = sorted(glob.glob(os.path.join(base, "*.png")))
    return {"ok": True, "files": files}


@APP.get("/lineage")
def get_lineage():
    """Return Memory Vault lineage index + suggested graph path."""
    idx = os.path.join("data", "memory_vault", "lineage_index.json")
    graph = os.path.join("data", "memory_vault", "lineage_graph.png")
    if not os.path.exists(idx):
        return {"ok": False, "error": "no lineage index"}
    with open(idx) as f:
        j = json.load(f)
    return {"ok": True, "index": j, "graph": graph if os.path.exists(graph) else None}


# ---------- New: canary promote ----------
class PromoteReq(BaseModel):
    target_tag: str


@APP.post("/canary_promote")
def canary_promote(req: PromoteReq, request: Request) -> dict:
    _check_auth(request)
    """Promote a canary model tag into active use."""
    cmd = "./ops/m11_canary_promote.sh " + shlex.quote(req.target_tag)
    try:
        subprocess.check_call(cmd, shell=True)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(500, f"promotion failed: {exc}") from exc
    else:
        return {"ok": True, "promoted": req.target_tag}


# ---------- Optional: flush guardrails ----------
@APP.post("/flush_guardrails")
def flush_guardrails():
    """Soft-reset guardrail counters (used for incident recovery testing)."""
    return {"ok": True, "flushed": True}


# ---------- T3: Health & readiness endpoints ----------
@APP.get("/healthz")
def healthz():
    """Fast health check - always returns ok."""
    return {"ok": True}


@APP.get("/health")
def health():
    return {"ops": "ok"}


# ---------------------------------------------------------------------------

SNAP_DIR = Path2("data/ops_snapshots")
SNAP_DIR.mkdir(parents=True, exist_ok=True)
RET_DAYS = int(os.getenv("SNAP_RETENTION_DAYS", "14"))

from ops.engine_client import get_portfolio  # noqa: E402
from ops.engine_client import health as engine_health  # noqa: E402

# globals for account cache
ACCOUNT_CACHE: dict = {
    "balances": {"equity": 0.0, "cash": 0.0, "exposure": 0.0},
    "pnl": {"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
    "positions": [],
    "ts": 0,
    "source": "engine",
}


# Command Center service wiring -------------------------------------------------
PORTFOLIO_SERVICE = PortfolioService()
ORDERS_SERVICE = OrdersService()
STRATEGY_SERVICE = StrategyGovernanceService(Path("ops/strategy_weights.json"))
SCANNER_SERVICE = ScannerService(Path("ops/universe_state.json"))
CONFIG_SERVICE = ConfigService(Path("config/runtime.yaml"), Path("ops/runtime_overrides.json"))
RISK_SERVICE = RiskGuardService()
FEEDS_SERVICE = FeedsGovernanceService()
OPS_SERVICE = OpsGovernanceService(STATE_FILE, engine_health, PORTFOLIO_SERVICE)

ui_state.configure(
    portfolio=PORTFOLIO_SERVICE,
    orders=ORDERS_SERVICE,
    strategy=STRATEGY_SERVICE,
    scanner=SCANNER_SERVICE,
    config=CONFIG_SERVICE,
    risk=RISK_SERVICE,
    feeds=FEEDS_SERVICE,
    ops=OPS_SERVICE,
)


def _update_metrics_account_fields(
    equity: float,
    cash: float,
    exposure: float,
    realized_pnl: float,
    unrealized_pnl: float,
) -> None:
    try:
        snap = _load_snap()
        metrics = snap.metrics.__dict__.copy()
        updated = False
        for key, val in {
            "account_equity_usd": float(equity),
            "cash_usd": float(cash),
            "gross_exposure_usd": float(exposure),
            "pnl_realized": float(realized_pnl),
            "pnl_unrealized": float(unrealized_pnl),
        }.items():
            if abs(metrics.get(key, 0.0) - val) > 1e-6:
                metrics[key] = val
                updated = True
        if updated:
            _save_snap(_Snapshot(metrics=_Metrics(**metrics), ts=time.time()))
    except (OSError, ValueError) as exc:
        print("account metrics update failed:", exc, flush=True)


def _publish_account_snapshot(state: dict) -> None:
    ACCOUNT_CACHE["equity"] = float(state.get("equity", 0.0))
    ACCOUNT_CACHE["cash"] = float(state.get("cash", 0.0))
    ACCOUNT_CACHE["exposure"] = float(state.get("exposure", 0.0))
    ACCOUNT_CACHE["pnl"] = state.get("pnl", {"realized": 0.0, "unrealized": 0.0, "fees": 0.0})
    ACCOUNT_CACHE["balances"] = {
        "equity": ACCOUNT_CACHE["equity"],
        "cash": ACCOUNT_CACHE["cash"],
        "exposure": ACCOUNT_CACHE["exposure"],
    }
    ACCOUNT_CACHE["positions"] = state.get("positions", [])
    ACCOUNT_CACHE["ts"] = state.get("ts", time.time())
    ACCOUNT_CACHE["source"] = state.get("source", "engine")
    PORTFOLIO_SERVICE.update_snapshot(ACCOUNT_CACHE)
    account_payload = {
        "type": "account",
        "equity": ACCOUNT_CACHE["equity"],
        "cash": ACCOUNT_CACHE["cash"],
        "exposure": ACCOUNT_CACHE["exposure"],
        "pnl": ACCOUNT_CACHE.get("pnl", {}),
        "positions": ACCOUNT_CACHE.get("positions", []),
        "ts": ACCOUNT_CACHE.get("ts"),
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and not loop.is_closed():
        loop.create_task(broadcast_account(account_payload))
    _update_metrics_account_fields(
        ACCOUNT_CACHE["equity"],
        ACCOUNT_CACHE["cash"],
        ACCOUNT_CACHE["exposure"],
        ACCOUNT_CACHE["pnl"]["realized"],
        ACCOUNT_CACHE["pnl"]["unrealized"],
    )


# engine-driven polling loop
async def _engine_poll_loop():
    engine_poll_errors = (httpx.HTTPError, ValueError, OSError)
    while True:
        try:
            portfolio = await get_portfolio()
            portfolio["source"] = "engine"
            _publish_account_snapshot(portfolio)
            await _persist_snapshot(portfolio)
        except engine_poll_errors as exc:
            print("engine poll error:", exc, flush=True)
        await asyncio.sleep(float(os.getenv("ENGINE_POLL_SEC", "2")))


async def _persist_snapshot(portfolio: dict) -> None:
    try:
        payload = {
            "ts": time.time(),
            "metrics": _load_snap().metrics.__dict__,
            "account": {
                "equity": portfolio.get("equity", 0.0),
                "cash": portfolio.get("cash", 0.0),
                "exposure": portfolio.get("exposure", 0.0),
                "positions": portfolio.get("positions", []),
                "pnl": portfolio.get("pnl", {}),
                "ts": portfolio.get("ts", time.time()),
            },
        }
        fn = SNAP_DIR / (time.strftime("%Y-%m-%d") + ".jsonl")
        with fn.open("a") as f:
            f.write(json.dumps(payload) + "\n")
        _trim_snapshots()
    except OSError as exc:
        print("snapshot persist failed:", exc, flush=True)


def _trim_snapshots() -> None:
    cutoff = time.time() - RET_DAYS * 86400
    for path in SNAP_DIR.glob("*.jsonl"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


# ---------- Risk Intelligence Daemon ----------
async def _risk_monitor_iteration() -> None:
    """Execute a single risk monitoring pass."""
    try:
        # Default aligns with tests/mock expectations
        ops_base = os.getenv("OPS_BASE", "http://localhost:8001").rstrip("/")
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{ops_base}/aggregate/exposure", timeout=5)
            r.raise_for_status()
            data = r.json() or {}

            alert_msg = None
            per_symbol = None
            if isinstance(data.get("by_symbol"), dict):
                per_symbol = list((data.get("by_symbol") or {}).values())
            elif isinstance(data.get("items"), list):
                per_symbol = list(data.get("items") or [])
            else:
                per_symbol = []

            for item in per_symbol:
                symbol = item.get("symbol", "UNKNOWN")
                try:
                    value_usd = abs(float(item.get("value_usd", 0.0)))
                except (TypeError, ValueError):
                    value_usd = 0.0
                if value_usd > RISK_LIMIT_USD:
                    alert_msg = f"🚨 RISK LIMIT BREACH: {symbol} exposure ${value_usd:.2f} > ${RISK_LIMIT_USD}"
                    break

            if alert_msg:
                print(f"[RISK] {alert_msg}")
                if ALERT_WEBHOOK_URL:
                    webhook_payload = {"text": alert_msg, "timestamp": time.time()}
                    try:
                        await client.post(ALERT_WEBHOOK_URL, json=webhook_payload, timeout=3)
                    except _HTTP_CLIENT_ERRORS as webhook_exc:
                        print(f"[RISK] Webhook failed: {webhook_exc}")

    except _HTTP_CLIENT_ERRORS as exc:
        print(f"[RISK] Monitor error: {exc}")


async def _risk_monitoring_loop(run_once: bool = False):
    """Background daemon that watches exposure and sends alerts."""
    if run_once:
        await _risk_monitor_iteration()
        return
    await asyncio.sleep(5)  # Delay startup to avoid race conditions
    while True:
        await _risk_monitor_iteration()
        await asyncio.sleep(EXPOSURE_CHECK_INTERVAL)


import fcntl as _fcntl  # noqa: E402
import os as _os  # noqa: E402

from ops.portfolio_collector import portfolio_collector_loop  # noqa: E402
from ops.strategy_selector import promote_best  # noqa: E402
from ops.strategy_tracker import strategy_tracker_loop  # noqa: E402

_TRACKER_LOCK_FD = None  # keep process-global lock handle alive


def _acquire_singleton_lock(name: str) -> bool:
    """Try to acquire a process-wide file lock so only one worker runs a task.

    Returns True if this process acquired the lock, False if another worker holds it.
    """
    global _TRACKER_LOCK_FD
    try:
        path = f"/tmp/{name}.lock"
        fd = _os.open(path, _os.O_CREAT | _os.O_RDWR)
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        _TRACKER_LOCK_FD = fd  # keep open to hold the lock
    except BlockingIOError:
        if "fd" in locals():
            with suppress(OSError):
                _os.close(fd)
        return False
    except OSError:
        return False
    else:
        return True


@APP.on_event("startup")
async def _start_poll():
    asyncio.create_task(_engine_poll_loop())
    asyncio.create_task(_risk_monitoring_loop())
    asyncio.create_task(exposure_collector_loop())
    asyncio.create_task(pnl_collector_loop())
    asyncio.create_task(portfolio_collector_loop())

    # Start strategy tracker in a single worker only (Option B)
    # Gate via env flag and file lock to ensure one-of-N under multiprocess uvicorn
    tracker_env_ok = _os.getenv("OPS_TRACKER_LEADER", "1").lower() in {
        "1",
        "true",
        "yes",
    }
    if tracker_env_ok and _acquire_singleton_lock("hmm_strategy_tracker"):
        asyncio.create_task(strategy_tracker_loop())
        print(f"[StrategyTracker] started in PID {_os.getpid()} (leader)")
    else:
        print(f"[StrategyTracker] skipped in PID {_os.getpid()} (follower)")


@APP.on_event("startup")
async def _start_ui_streams():
    asyncio.create_task(account_broadcaster(PORTFOLIO_SERVICE))
    symbols = default_symbols()
    if symbols:
        asyncio.create_task(price_stream(symbols))


@APP.on_event("startup")
async def _start_canary_manager():
    """Start the canary deployment evaluation daemon."""
    try:
        from ops.canary_manager import canary_evaluation_loop

        asyncio.create_task(canary_evaluation_loop())
        print("[CANARY] Canary manager started - continuous model evaluation active")
    except ImportError as exc:
        print(f"[WARN] Canary manager startup failed: {exc}")


@APP.on_event("startup")
async def _start_capital_allocator():
    """Start the dynamic capital allocation daemon."""
    try:
        from ops.capital_allocator import allocation_loop

        asyncio.create_task(allocation_loop())
        print("[ALLOC] Capital allocator started - dynamic capital optimization active")
    except ImportError as exc:
        print(f"[WARN] Capital allocator startup failed: {exc}")


@APP.on_event("startup")
async def _start_strategy_governance():
    # Strategy promotion loop - evaluates every 60 seconds
    async def promotion_loop():
        await asyncio.sleep(5)  # Let system warm up
        import os

        enabled = os.getenv("GOVERNANCE_PROMOTE_ENABLED", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        while True:
            try:
                if enabled:
                    promote_best()
                await asyncio.sleep(60)
            except (RuntimeError, ValueError) as exc:
                logging.warning("[Governance] Promoter error: %s", exc)
                await asyncio.sleep(30)  # Retry sooner on error

    asyncio.create_task(promotion_loop())


# expose account endpoints
@APP.get("/account_snapshot")
def account_snapshot():
    return ACCOUNT_CACHE


@APP.get("/positions")
def positions():
    return {"positions": ACCOUNT_CACHE.get("positions", [])}


ACC = None  # Remove legacy BinanceAccountProvider instantiation to prevent import-time crash


# ---------- Multi-Venue Aggregation Endpoints ----------
async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        r = await client.get(url, timeout=3)
        r.raise_for_status()
        data = r.json()
    except _HTTP_CLIENT_ERRORS as exc:
        logging.debug("aggregate fetch failed for %s: %s", url, exc)
        return {}
    else:
        logging.debug("aggregate fetch success for %s: %s", url, data)
        return data


async def _fetch_many(paths: list[str]) -> list[dict[str, Any]]:
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits, trust_env=True) as client:
        coros = [_fetch_json(client, p) for p in paths]
        results = await asyncio.gather(*coros, return_exceptions=True)

    normalized: list[dict[str, Any]] = []
    for path, result in zip(paths, results, strict=False):
        if isinstance(result, dict):
            normalized.append(result)
            continue
        logging.warning("aggregate fetch unexpected failure for %s: %s", path, result)
        normalized.append({})
    return normalized


@APP.get("/aggregate/health")
async def aggregate_health():
    endpoints = engine_endpoints()
    results = await _fetch_many([f"{e}/health" for e in endpoints])
    return {"venues": results}


@APP.get("/aggregate/portfolio")
async def aggregate_portfolio():
    endpoints = engine_endpoints()
    portfolios = await _fetch_many([f"{e}/portfolio" for e in endpoints])
    total_equity = sum(float(p.get("equity_usd", 0) or 0) for p in portfolios if p)
    metrics_view = get_portfolio_snapshot()
    return {
        "total_equity_usd": total_equity,
        "venues": portfolios,
        "count": len([p for p in portfolios if p]),
        **metrics_view,
    }


# Use the new comprehensive exposure aggregator
from ops.aggregate_exposure import aggregate_exposure  # noqa: E402
from ops.exposure_collector import exposure_collector_loop  # noqa: E402
from ops.pnl_collector import pnl_collector_loop  # noqa: E402


@APP.get("/aggregate/exposure")
async def get_aggregate_exposure():
    """
    Unified exposure aggregator: merges positions from all engines (Binance + IBKR),
    fills missing IBKR prices from live publisher, includes watchlist symbols.
    """
    agg = await aggregate_exposure(engine_endpoints_env=os.getenv("ENGINE_ENDPOINTS"))
    return {
        "totals": agg.totals,
        "by_symbol": agg.by_symbol,
    }


@APP.get("/aggregate/metrics")
async def aggregate_metrics():
    endpoints = engine_endpoints()
    metrics = await _fetch_many([f"{e}/metrics" for e in endpoints])
    return {"venues": metrics}


@APP.get("/aggregate/pnl")
def get_pnl_snapshot():
    """
    Unified PnL snapshot: returns realized and unrealized PnL per venue.
    Uses PROMETHEUS_METRICS direct from pnl_collector for accuracy.
    """
    out = {"realized": {}, "unrealized": {}}
    for metric in PNL_REALIZED.collect():
        for sample in metric.samples:
            out["realized"][sample.labels["venue"]] = float(sample.value)
    for metric in PNL_UNREALIZED.collect():
        for sample in metric.samples:
            out["unrealized"][sample.labels["venue"]] = float(sample.value)
    return out


@APP.get("/aggregate/portfolio")
def get_portfolio_snapshot():
    """
    Portfolio snapshot: total equity, cash, gain/loss, and return % since daily baseline.
    Handy for your Dash to show equity card with current portfolio performance.
    """
    return {
        "equity_usd": float(PORTFOLIO_EQUITY._value.get()),
        "cash_usd": float(PORTFOLIO_CASH._value.get()),
        "gain_usd": float(PORTFOLIO_GAIN._value.get()),
        "return_pct": float(PORTFOLIO_RET._value.get()),
        "baseline_equity_usd": float(PORTFOLIO_PREV._value.get()),
        "last_refresh_epoch": (
            float(PORTFOLIO_LAST._value.get()) if PORTFOLIO_LAST._value.get() else None
        ),
    }


# ---------- Strategy Governance Dashboard Endpoints ----------

# Import strategy governance functions
from ops.strategy_selector import get_leaderboard  # noqa: E402


# Leaderboard endpoint - core governance API
@APP.get("/strategy/leaderboard")
def get_strategy_leaderboard():
    """Return live strategy leaderboard with performance rankings."""
    leaderboard = get_leaderboard()
    return {"ok": True, "leaderboard": leaderboard}


# Status endpoint with full registry
@APP.get("/strategy/status")
def get_strategy_status():
    """Return current strategy registry and leaderboard."""
    registry_path = Path("ops/strategy_registry.json")
    if not registry_path.exists():
        return {"error": "strategy registry not found"}
    try:
        registry = json.loads(registry_path.read_text())
    except json.JSONDecodeError:
        return {"error": "invalid registry format"}

    return {"registry": registry, "leaderboard": get_leaderboard(), "ts": time.time()}


# Promotion history endpoint
@APP.get("/strategy/history")
def get_promotion_history():
    """Return chronological log of all strategy promotions."""
    registry_path = Path("ops/strategy_registry.json")
    if not registry_path.exists():
        return {"error": "strategy registry not found"}
    try:
        registry = json.loads(registry_path.read_text())
    except json.JSONDecodeError as exc:
        return {"error": str(exc)}
    else:
        return {"ok": True, "promotion_log": registry.get("promotion_log", [])}


@APP.get("/strategy/ui")
def get_strategy_ui():
    """Return HTML dashboard for strategy governance visualization."""
    from ops.strategy_ui import get_strategy_ui_html

    try:
        return get_strategy_ui_html()
    except (RuntimeError, ValueError, OSError) as exc:
        return f"<html><body><h1>Error Loading Dashboard</h1><p>{str(exc)[:200]}</p></body></html>"


@APP.post("/strategy/promote")
def manual_promote_strategy(req: dict, request: Request):
    """Manually promote a specific strategy to production."""
    _check_auth(request)

    model_tag = req.get("model_tag")
    if not model_tag:
        return {"error": "model_tag required"}

    from ops.strategy_selector import load_registry, save_registry

    min_t = 3  # Require at least 3 trades for promotion when not manual

    try:
        registry = load_registry()
        stats = registry.get(model_tag)
        if stats is None:
            stats = {
                "sharpe": 0.0,
                "drawdown": 0.0,
                "realized": 0.0,
                "trades": 0,
                "manual": True,
                "last_pnl": 0.0,
                "samples": [],
            }
            registry[model_tag] = stats

        # Manual override defaults to True for this endpoint
        stats["manual"] = True

        if stats.get("trades", 0) < min_t and not stats.get("manual"):
            return {"error": f"model needs at least {min_t} trades to promote"}

        # Set as current
        registry["current_model"] = model_tag
        save_registry(registry)

        # Broadcast to engines
        import asyncio

        from ops.strategy_selector import push_model_update

        asyncio.run(push_model_update(model_tag))

    except (OSError, ValueError, RuntimeError) as exc:
        return {"error": str(exc)}
    else:
        return {"ok": True, "promoted": model_tag, "trades_required": min_t}


# WebSocket proxies for the Command Center UI


@APP.websocket("/ws/price")
async def _ws_price(websocket: WebSocket):
    await ws_price(websocket)


@APP.websocket("/ws/account")
async def _ws_account(websocket: WebSocket):
    await ws_account(websocket)


@APP.websocket("/ws/orders")
async def _ws_orders(websocket: WebSocket):
    await ws_orders(websocket)


@APP.websocket("/ws/trades")
async def _ws_trades(websocket: WebSocket):
    await ws_trades(websocket)


@APP.websocket("/ws/events")
async def _ws_events(websocket: WebSocket):
    await ws_events(websocket)


# Mount the new Command Center single-page app
APP.mount("/", StaticFiles(directory="ops/static_ui", html=True), name="ui")


# ---- Situations SSE consumer (shadow mode) ----
SSE_COUNTER = get_or_create_counter(
    "situation_events_consumed_total",
    "Number of situation events consumed by Ops",
    labelnames=("name",),
)


@APP.on_event("startup")
async def _start_situations_consumer():
    async def _run():
        import httpx

        url = os.getenv("SITUATIONS_SSE_URL", "http://hmm_situations:8011/events/stream")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", url) as r:
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        try:
                            evt = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        name = evt.get("situation") or "unknown"
                        SSE_COUNTER.labels(name=name).inc()
        except _HTTP_CLIENT_ERRORS as exc:
            print(f"[SITUATIONS] SSE consumer error: {exc}")

    asyncio.create_task(_run())


# FastAPI expects `app` attribute in some tests/utilities.
app = APP

# ---- Multiplexed WebSocket aggregator for UI (Option A) ----


@APP.websocket("/ws")
async def ws_multiplex(websocket: WebSocket):
    """
    Single WebSocket endpoint that periodically pushes compact UI-friendly updates:
      - type: 'metrics'      data: GlobalMetrics (see frontend types)
      - type: 'venues'       data: list[Venue]
      - type: 'heartbeat'    data: { ts }

    Auth: accepts `?token=...` matching OPS_API_TOKEN. In dev, missing token is allowed.
    """
    import time as _time

    # Lightweight auth: allow missing token when using default dev token
    token = websocket.query_params.get("token")
    expected = get_expected_token()
    dev_mode = expected == "dev-token"
    if token is not None and token != expected:
        await websocket.close(code=4401)
        return
    if token is None and not dev_mode:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    # Subscription set (currently informational)
    channels = {"metrics", "venues"}

    async def _push_metrics_loop():
        while True:
            try:
                # Pull summary KPIs via local HTTP to reuse existing logic
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get("http://127.0.0.1:8002/api/metrics/summary")
                    j = r.json() if r.status_code == 200 else {}
                kpis = j.get("kpis") or {}

                # Portfolio return_pct/gain via direct registry snapshot
                port = get_portfolio_snapshot()

                data = {
                    "totalPnL": float(kpis.get("totalPnl") or 0.0),
                    "totalPnLPercent": float(port.get("return_pct") or 0.0),
                    "sharpe": float(kpis.get("sharpe") or 0.0),
                    "drawdown": float(kpis.get("maxDrawdown") or 0.0),
                    "activePositions": int(kpis.get("openPositions") or 0),
                    "dailyTradeCount": 0,
                }
                msg = {
                    "type": "metrics",
                    "data": data,
                    "timestamp": int(_time.time() * 1000),
                }
                if "metrics" in channels:
                    await websocket.send_json(msg)
            except WebSocketDisconnect:
                break
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(3)
                continue
            await asyncio.sleep(3)

    async def _push_venues_loop():
        while True:
            try:
                h = await cc_health()  # Reuse existing aggregator
                venues = []
                for v in h.get("venues", []) or []:
                    status = str(v.get("status") or "warn").lower()
                    mapped = (
                        "connected"
                        if status == "ok"
                        else ("degraded" if status == "warn" else "offline")
                    )
                    venues.append(
                        {
                            "id": str(v.get("name") or "engine").lower(),
                            "name": v.get("name") or "engine",
                            "type": "crypto",
                            "status": mapped,
                            "latency": int(float(v.get("latencyMs") or 0)),
                        }
                    )
                msg = {
                    "type": "venues",
                    "data": venues,
                    "timestamp": int(_time.time() * 1000),
                }
                if "venues" in channels:
                    await websocket.send_json(msg)
            except WebSocketDisconnect:
                break
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(5)

    async def _recv_loop():
        while True:
            try:
                incoming = await websocket.receive_json()
                t = incoming.get("type")
                if t == "subscribe":
                    req = set(incoming.get("channels") or [])
                    # Only allow known channels
                    channels.clear()
                    channels.update({c for c in req if c in {"metrics", "venues", "performances"}})
                    # Ack optional
                elif t == "heartbeat":
                    await websocket.send_json(
                        {"type": "heartbeat", "timestamp": int(_time.time() * 1000)}
                    )
                else:
                    # Ignore unknown message types
                    pass
            except WebSocketDisconnect:
                break
            except (json.JSONDecodeError, TypeError):
                # Malformed payloads are ignored
                continue

    # Run loops until client disconnects
    metrics_task = asyncio.create_task(_push_metrics_loop())
    venues_task = asyncio.create_task(_push_venues_loop())
    try:
        await _recv_loop()
    finally:
        metrics_task.cancel()
        venues_task.cancel()
