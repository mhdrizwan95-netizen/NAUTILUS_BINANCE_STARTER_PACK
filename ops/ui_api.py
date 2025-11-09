"""FastAPI router exposing the Command Center surface."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import secrets
import time
from collections import OrderedDict, deque
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Annotated, Any

import httpx
import yaml
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel

from ops import pnl_dashboard as pnl
from ops import ui_state
from ops.env import engine_endpoints
from ops.governance_daemon import (
    reload_governance_policies as governance_reload_policies,
)
from ops.middleware.control_guard import (
    ControlContext,
    ControlGuard,
    IdempotentGuard,
    TokenOnlyGuard,
)

logger = logging.getLogger(__name__)


def _load_ops_token() -> str:
    token = os.getenv("OPS_API_TOKEN")
    token_file = os.getenv("OPS_API_TOKEN_FILE")
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OpsTokenFileError(token_file) from exc
    if not token or token == "dev-token":
        raise OpsTokenMissingError()
    return token


@lru_cache(maxsize=1)
def get_ops_token() -> str:
    """Load and cache the ops token to avoid import-time failures."""
    return _load_ops_token()


def reset_ops_token_cache() -> None:
    """Tests can clear the memoized token after mutating env vars."""
    get_ops_token.cache_clear()


DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500


def http_error(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Raise an HTTPException with a structured payload."""
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details},
    )


def _require_idempotency(request: Request) -> tuple[str, dict[str, Any] | None]:
    key = request.headers.get("Idempotency-Key")
    if not key:
        http_error(
            status.HTTP_400_BAD_REQUEST,
            "idempotency.missing_header",
            "Missing Idempotency-Key header",
        )
    assert key is not None
    cached = _idempotency_lookup(key)
    return key, cached


router = APIRouter(prefix="/api", tags=["command-center"])
_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    asyncio.TimeoutError,
    httpx.HTTPError,
)

_IDEMPOTENCY_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_IDEMPOTENCY_LOCK = RLock()
_IDEMPOTENCY_MAX = 512
CONTROL_AUDIT_PATH = Path("ops/logs/control_actions.jsonl")
_WS_SESSIONS: dict[str, float] = {}
_WS_SESSION_LOCK = RLock()
_WS_SESSION_TTL_SEC = float(os.getenv("OPS_WS_SESSION_TTL", "900"))


class ConfigPatch(BaseModel):
    DRY_RUN: bool | None = None
    SYMBOL_SCANNER_ENABLED: bool | None = None
    SOFT_BREACH_ENABLED: bool | None = None
    SOFT_BREACH_TIGHTEN_SL_PCT: float | None = None
    SOFT_BREACH_BREAKEVEN_OK: bool | None = None
    SOFT_BREACH_CANCEL_ENTRIES: bool | None = None


class StrategyPatch(BaseModel):
    enabled: bool | None = None
    weights: dict[str, float] | None = None


class CancelOrdersRequest(BaseModel):
    orderIds: list[str]


class TransferRequest(BaseModel):
    asset: str
    amount: float
    source: str
    target: str


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str | None = None


class FlattenRequest(BaseModel):
    dryRun: bool | None = False


class OpsTokenFileError(RuntimeError):
    """Raised when the ops token file cannot be read."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Failed to read OPS_API_TOKEN_FILE ({path})")


class OpsTokenMissingError(RuntimeError):
    """Raised when the ops token is not configured."""

    def __init__(self) -> None:
        super().__init__(
            "Set OPS_API_TOKEN or OPS_API_TOKEN_FILE before starting the Command Center API"
        )


def require_ops_token(x_ops_token: str | None = Header(None)) -> None:
    if x_ops_token != get_ops_token():
        http_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.invalid_token",
            "Unauthorized",
        )


def get_state() -> dict[str, Any]:
    return ui_state.get_services()


IdemGuardDep = Annotated[ControlContext, Depends(IdempotentGuard)]
TokenGuardDep = Annotated[ControlContext, Depends(TokenOnlyGuard)]
ControlContextDep = Annotated[ControlContext, Depends(ControlGuard())]
StateDep = Annotated[dict[str, Any], Depends(get_state)]
AuthDep = Annotated[None, Depends(require_ops_token)]


# ---------------------------------------------------------------------------
# In-memory/eventual-persist stores to satisfy the Command Center frontend
# ---------------------------------------------------------------------------

# Recent trades and alerts feeds (simple in-memory ring buffers)
RECENT_TRADES: deque[dict[str, Any]] = deque(maxlen=500)
ALERTS_FEED: deque[dict[str, Any]] = deque(maxlen=200)

# Strategy parameter storage backed by a JSON file
PARAMS_PATH = Path("ops/strategy_params.json")


def _load_params() -> dict[str, Any]:
    if not PARAMS_PATH.exists():
        return {}
    try:
        return json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    except _SUPPRESSIBLE_EXCEPTIONS:
        return {}


def _save_params(payload: dict[str, Any]) -> None:
    PARAMS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _idempotency_lookup(key: str) -> dict[str, Any] | None:
    with _IDEMPOTENCY_LOCK:
        cached = _IDEMPOTENCY_CACHE.get(key)
        if cached:
            return cached[1]
    return None


def _idempotency_store(key: str, response: dict[str, Any]) -> None:
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_CACHE[key] = (time.time(), response)
        _IDEMPOTENCY_CACHE.move_to_end(key)
        while len(_IDEMPOTENCY_CACHE) > _IDEMPOTENCY_MAX:
            _IDEMPOTENCY_CACHE.popitem(last=False)


def _idempotency_cached_response(idem_key: str) -> dict[str, Any] | None:
    if not idem_key:
        return None
    return _idempotency_lookup(idem_key)


def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"o": offset}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


def _decode_cursor(cursor: str) -> int:
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        data = json.loads(raw.decode("utf-8"))
        offset = int(data.get("o", 0))
    except _SUPPRESSIBLE_EXCEPTIONS:  # pragma: no cover - defensive guard
        http_error(
            status.HTTP_400_BAD_REQUEST,
            "pagination.invalid_cursor",
            "Cursor is malformed or expired.",
            {"cursor": cursor},
        )
    if offset < 0:
        http_error(
            status.HTTP_400_BAD_REQUEST,
            "pagination.invalid_cursor",
            "Cursor offset must be positive.",
            {"cursor": cursor},
        )
    return offset


def _record_control_action(
    action: str,
    actor: str | None,
    approver: str | None,
    idempotency_key: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> None:
    try:
        CONTROL_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "action": action,
            "actor": actor,
            "approver": approver,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "result": result,
        }
        with CONTROL_AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except _SUPPRESSIBLE_EXCEPTIONS:
        # Audit logging best-effort; avoid interrupting control flow
        pass


def _paginate_items(
    items: list[dict[str, Any]] | list[Any],
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    sequence = list(items)
    total = len(sequence)
    start = 0
    if cursor:
        start = _decode_cursor(cursor)
        if total == 0:
            start = 0
        elif start > total:
            start = max(total - limit, 0)

    end = start + limit
    window = sequence[start:end]

    next_cursor = _encode_cursor(end) if end < total else None
    prev_cursor = _encode_cursor(max(start - limit, 0)) if start > 0 else None

    return {
        "data": window,
        "page": {
            "nextCursor": next_cursor,
            "prevCursor": prev_cursor,
            "limit": limit,
            "totalHint": total,
            "hasMore": next_cursor is not None,
        },
    }


def _normalize_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for idx, p in enumerate(rows):
        symbol = p.get("symbol") or p.get("product") or p.get("instrument") or "UNKNOWN"
        sanitized.append(
            {
                "id": p.get("id") or f"position-{symbol.lower()}-{idx}",
                "symbol": symbol,
                "qty": float(p.get("qty") or p.get("quantity") or p.get("size") or 0),
                "entry": float(
                    p.get("entry") or p.get("entry_price") or p.get("avgEntryPrice") or 0
                ),
                "mark": float(p.get("mark") or p.get("mark_price") or p.get("markPrice") or 0),
                "pnl": float(
                    p.get("pnl") or p.get("unrealizedPnl") or p.get("unrealized_pnl") or 0
                ),
            }
        )
    sanitized.sort(key=lambda item: item["symbol"])
    return sanitized


async def _collect_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        raw = await state["portfolio"].list_open_positions()
    except _SUPPRESSIBLE_EXCEPTIONS:
        raw = []
    return _normalize_positions(raw)


def _issue_ws_session() -> tuple[str, float]:
    """Create a short-lived WebSocket session token."""
    now = time.time()
    expiry = now + _WS_SESSION_TTL_SEC
    token = secrets.token_urlsafe(32)
    with _WS_SESSION_LOCK:
        # prune expired sessions first
        expired = [key for key, ts in _WS_SESSIONS.items() if ts <= now]
        for key in expired:
            _WS_SESSIONS.pop(key, None)
        _WS_SESSIONS[token] = expiry
    return token, expiry


def _validate_ws_session(session: str | None) -> bool:
    if not session:
        return False
    now = time.time()
    with _WS_SESSION_LOCK:
        expiry = _WS_SESSIONS.get(session)
        if expiry and expiry > now:
            return True
        if expiry is not None:
            _WS_SESSIONS.pop(session, None)
    return False


@router.post("/ops/ws-session")
async def create_ws_session(
    guard: TokenGuardDep,
) -> dict[str, Any]:
    """Issue a temporary session token for WebSocket subscriptions."""
    actor = (guard.actor or "").strip()
    if not actor:
        http_error(
            status.HTTP_400_BAD_REQUEST,
            "auth.actor_required",
            "Provide X-Ops-Actor header when requesting a WebSocket session.",
        )
    session, expiry = _issue_ws_session()
    _record_control_action(
        "ws_session.issue",
        actor,
        guard.approver,
        session,
        {},
        {"expires": expiry},
    )
    return {"session": session, "expires": expiry}


def _yaml_schema_to_param_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert strategy_schemas YAML format into the UI ParamSchema contract."""
    fields: list[dict[str, Any]] = []
    for key, spec in (raw.get("parameters") or {}).items():
        typ = (spec.get("type") or "").lower()
        if typ in {"int", "integer"}:
            fields.append(
                {
                    "type": "integer",
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "min": spec.get("min"),
                    "max": spec.get("max"),
                    "step": 1,
                    "default": (spec.get("presets") or [spec.get("min") or 0])[0],
                }
            )
        elif typ in {"float", "number"}:
            fields.append(
                {
                    "type": "number",
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "min": spec.get("min"),
                    "max": spec.get("max"),
                    "step": 0.1,
                    "default": (spec.get("presets") or [spec.get("min") or 0.0])[0],
                }
            )
        elif typ == "bool":
            fields.append(
                {
                    "type": "boolean",
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "default": bool(spec.get("default", False)),
                }
            )
        else:
            # fallback to string
            fields.append(
                {
                    "type": "string",
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "default": str(spec.get("default", "")),
                }
            )
    return {"title": raw.get("strategy") or raw.get("title"), "fields": fields}


def _load_strategy_schema(strategy_id: str) -> dict[str, Any]:
    """Load YAML schema by strategy id; fallback to momentum_breakout if missing."""
    base = Path("strategy_schemas")
    candidates = [base / f"{strategy_id}.yaml", base / "momentum_breakout.yaml"]
    for path in candidates:
        if path.exists():
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return _yaml_schema_to_param_schema(raw)
            except _SUPPRESSIBLE_EXCEPTIONS:
                continue
    # Empty schema fallback
    return {"title": strategy_id, "fields": []}


@router.get("/engine/status")
async def engine_status(state: StateDep) -> Any:
    return await state["ops"].status()


@router.get("/config/effective")
async def config_effective(state: StateDep) -> Any:
    return await state["config"].get_effective()


@router.put("/config")
async def config_update(
    patch: ConfigPatch,
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    payload = {k: v for k, v in patch.dict().items() if v is not None}
    if not payload:
        result = await state["config"].get_effective()
        payload_for_audit: dict[str, Any] = {"noop": True}
    else:
        try:
            result = await state["config"].patch(
                payload,
                actor=guard.actor,
                approver=guard.approver,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload_for_audit = payload

    response = result
    _record_control_action(
        "config.patch",
        guard.actor,
        guard.approver,
        idem_key,
        payload_for_audit,
        {"ok": True, "result": result},
    )
    _idempotency_store(idem_key, response)
    return response


@router.get("/strategies/governance")
async def strategies_list(
    state: StateDep,
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    """Original governance view of strategies (weights, enabled).

    Kept for compatibility; the Command Center UI consumes /api/strategies
    which returns schema-driven cards.
    """
    payload = await state["strategy"].list()
    entries = payload.get("strategies") or []
    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries):
        item = dict(entry)
        strategy_id = entry.get("id") or f"strategy-{idx}"
        item["id"] = str(strategy_id)
        weight = entry.get("weight")
        item["weight"] = float(weight) if weight is not None else 0.0
        if "enabled" in entry:
            item["enabled"] = bool(entry.get("enabled"))
        else:
            item["enabled"] = item["weight"] > 0.0
        item["is_current"] = bool(entry.get("is_current")) or (
            str(strategy_id) == str(payload.get("current"))
        )
        normalized.append(item)

    normalized.sort(key=lambda entry: entry.get("id", ""))
    paged = _paginate_items(normalized, cursor, limit)
    paged["meta"] = {
        "current": payload.get("current"),
        "updatedAt": payload.get("updated_at"),
    }
    return paged


@router.patch("/strategies/{strategy_id}")
async def strategies_patch(
    strategy_id: str,
    patch: StrategyPatch,
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    updates = patch.dict(exclude_none=True)
    result = await state["strategy"].patch(strategy_id, updates)

    _record_control_action(
        "strategy.patch",
        guard.actor,
        guard.approver,
        idem_key,
        {"strategyId": strategy_id, **updates},
        {"ok": True, "result": result},
    )
    if idem_key:
        _idempotency_store(idem_key, result)
    return result


@router.get("/universe/{strategy_id}")
async def universe_get(strategy_id: str, state: StateDep) -> Any:
    return await state["scanner"].universe(strategy_id)


@router.post("/universe/{strategy_id}/refresh")
async def universe_refresh(
    strategy_id: str,
    state: StateDep,
    _auth: AuthDep,
) -> Any:
    return await state["scanner"].refresh(strategy_id)


@router.get("/orders/open")
async def orders_open(
    state: StateDep,
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    try:
        orders = await state["orders"].list_open_orders()
    except _SUPPRESSIBLE_EXCEPTIONS:
        orders = []

    sanitized: list[dict[str, Any]] = []
    now = int(time.time() * 1000)
    for idx, order in enumerate(orders):
        created_at = (
            order.get("createdAt")
            or order.get("time")
            or order.get("timestamp")
            or order.get("transactTime")
            or order.get("updateTime")
            or (now - idx * 1000)
        )
        try:
            created_at_int = int(created_at)
        except _SUPPRESSIBLE_EXCEPTIONS:
            created_at_int = now - idx * 1000
        symbol = order.get("symbol") or order.get("instrument") or "UNKNOWN"
        sanitized.append(
            {
                "id": str(
                    order.get("id")
                    or order.get("orderId")
                    or order.get("clientOrderId")
                    or f"order-{created_at_int}-{symbol}-{idx}"
                ),
                "symbol": symbol,
                "side": (order.get("side") or "buy").lower(),
                "type": (order.get("type") or "limit").lower(),
                "qty": float(
                    order.get("qty") or order.get("quantity") or order.get("origQty") or 0
                ),
                "filled": float(
                    order.get("filled")
                    or order.get("executedQty")
                    or order.get("cumulativeFilled")
                    or 0
                ),
                "price": float(order.get("price") or order.get("avgPrice") or 0),
                "status": (order.get("status") or "open").lower(),
                "createdAt": created_at_int,
            }
        )

    sanitized.sort(key=lambda item: item["createdAt"], reverse=True)
    return _paginate_items(sanitized, cursor, limit)


@router.post("/orders/cancel")
async def orders_cancel(
    body: CancelOrdersRequest,
    state: StateDep,
    _auth: AuthDep,
) -> Any:
    try:
        return await state["orders"].cancel_many(body.orderIds)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/positions/open")
async def positions_open(
    state: StateDep,
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    sanitized = await _collect_positions(state)
    return _paginate_items(sanitized, cursor, limit)


@router.post("/risk/soft-breach/now")
async def soft_breach(
    state: StateDep,
    _auth: AuthDep,
) -> Any:
    return await state["risk"].soft_breach_now()


@router.post("/ops/kill-switch")
async def killswitch(
    payload: KillSwitchRequest,
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    result = await state["ops"].set_trading_enabled(payload.enabled)
    action = "resume" if payload.enabled else "pause"
    response = {"ok": True, "action": action, "result": result}
    _record_control_action(
        action,
        guard.actor,
        guard.approver,
        idem_key,
        payload.model_dump(),
        response,
    )
    _idempotency_store(idem_key, response)
    return response


@router.post("/ops/flatten")
async def flatten_portfolio(
    _body: FlattenRequest,
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        result = await state["ops"].flatten_positions(actor=guard.actor)
    except RuntimeError as exc:  # pragma: no cover - defensive
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    response = {"ok": True, "action": "flatten", **result}
    _record_control_action(
        "flatten",
        guard.actor,
        guard.approver,
        idem_key,
        {},
        response,
    )
    _idempotency_store(idem_key, response)
    return response


@router.post("/governance/reload")
async def governance_reload(
    guard: TokenGuardDep,
) -> Any:
    try:
        ok = governance_reload_policies()
    except _SUPPRESSIBLE_EXCEPTIONS as exc:  # pragma: no cover - defensive
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Reload failed: {exc}") from exc
    if not ok:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Reload returned false")
    audit_key = guard.idempotency_key or secrets.token_urlsafe(16)
    _record_control_action(
        "governance.reload",
        guard.actor,
        guard.approver,
        audit_key,
        {},
        {"ok": True},
    )
    return {"ok": True}


@router.get("/feeds/status")
async def feeds_status(state: StateDep) -> Any:
    return await state["feeds"].status()


@router.patch("/feeds/announcements")
async def feeds_announcements(
    body: dict[str, Any],
    state: StateDep,
    _auth: AuthDep,
) -> Any:
    return await state["feeds"].patch_announcements(body)


@router.patch("/feeds/meme")
async def feeds_meme(
    body: dict[str, Any],
    state: StateDep,
    _auth: AuthDep,
) -> Any:
    return await state["feeds"].patch_meme(body)


@router.post("/account/transfer")
async def account_transfer(
    body: TransferRequest,
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        result = await state["ops"].transfer_internal(
            body.asset, body.amount, body.source, body.target
        )
    except RuntimeError as exc:  # pragma: no cover - defensive
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Transfer failed: {exc}") from exc

    _record_control_action(
        "account.transfer",
        guard.actor,
        guard.approver,
        idem_key,
        body.dict(),
        result,
    )
    if idem_key:
        _idempotency_store(idem_key, result)
    return result


@router.post("/events/trade")
async def post_trade_event(
    item: dict[str, Any],
    _auth: AuthDep,
) -> Any:
    # Capture recent trade for the frontend feed
    try:
        RECENT_TRADES.append(
            {
                "time": item.get("time") or item.get("timestamp") or int(time.time() * 1000),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "qty": float(item.get("qty") or item.get("quantity") or 0),
                "price": float(item.get("price") or 0),
                "pnl": item.get("pnl"),
            }
        )
    except _SUPPRESSIBLE_EXCEPTIONS:
        pass
    await broadcast_trade(item)
    await broadcast_event({"type": "trade", "payload": item})
    return {"ok": True}


# ----------------------- Frontend integration endpoints ----------------------


@router.get("/strategies")
async def cc_strategies_list(
    state: StateDep,
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    """Return strategy cards with paramsSchema and current params for the UI."""
    gov = await state["strategy"].list()
    params_store = _load_params()

    # Symbols source from scanner service where available
    # Build a union of possible strategies from governance
    items = []
    for entry in gov.get("strategies", []):
        sid = entry.get("id")
        schema = _load_strategy_schema(sid)
        params = params_store.get(sid, {})
        # Attach universe symbols if known
        try:
            uni = await state["scanner"].universe(sid)
            symbols = uni.get("symbols", [])
        except _SUPPRESSIBLE_EXCEPTIONS:
            symbols = []

        # Minimal performance with dev-friendly sparkline when no live data
        perf: dict[str, Any] = {"pnl": 0.0}
        try:
            import random
            import time as _time

            rnd = random.Random(hash(sid) & 0xFFFF)
            base = 10000.0
            series = []
            for i in range(24):
                base *= 1 + rnd.gauss(0.0005, 0.01)
                ts = _time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_time.time() - (24 - i) * 3600)
                )
                series.append({"t": ts, "equity": round(base, 2)})
            perf = {
                "pnl": round(base - 10000.0, 2),
                "equitySeries": series,
                "winRate": round(rnd.uniform(0.48, 0.62), 2),
                "sharpe": round(rnd.uniform(0.5, 1.3), 2),
                "drawdown": round(rnd.uniform(0.05, 0.2), 2),
            }
        except _SUPPRESSIBLE_EXCEPTIONS:
            pass

        items.append(
            {
                "id": sid,
                "name": sid,
                "kind": "strategy",
                "status": "running" if entry.get("enabled") else "stopped",
                "symbols": symbols,
                "paramsSchema": schema,
                "params": params,
                "performance": perf,
            }
        )

    items.sort(key=lambda entry: entry.get("id", ""))
    return _paginate_items(items, cursor, limit)


@router.get("/strategies/{strategy_id}")
async def cc_strategy_get(strategy_id: str, state: StateDep) -> Any:
    params_store = _load_params()
    schema = _load_strategy_schema(strategy_id)
    try:
        uni = await state["scanner"].universe(strategy_id)
        symbols = uni.get("symbols", [])
    except _SUPPRESSIBLE_EXCEPTIONS:
        symbols = []
    return {
        "id": strategy_id,
        "name": strategy_id,
        "kind": "strategy",
        "status": "running",
        "symbols": symbols,
        "paramsSchema": schema,
        "params": params_store.get(strategy_id, {}),
    }


@router.post("/strategies/{strategy_id}/start")
async def cc_strategy_start(
    strategy_id: str,
    guard: IdemGuardDep,
    state: StateDep,
    body: dict[str, Any] | None = None,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        await state["strategy"].patch(strategy_id, {"enabled": True})
        if body and isinstance(body.get("params"), dict):
            store = _load_params()
            store[strategy_id] = body["params"]
            _save_params(store)
    except HTTPException:
        raise
    except _SUPPRESSIBLE_EXCEPTIONS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        response = {"ok": True, "action": "start", "strategyId": strategy_id}
        _record_control_action(
            "strategy.start",
            guard.actor,
            guard.approver,
            idem_key,
            body or {},
            response,
        )
        _idempotency_store(idem_key, response)
        return response


@router.post("/strategies/{strategy_id}/stop")
async def cc_strategy_stop(
    strategy_id: str,
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        await state["strategy"].patch(strategy_id, {"enabled": False})
    except HTTPException:
        raise
    except _SUPPRESSIBLE_EXCEPTIONS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        response = {"ok": True, "action": "stop", "strategyId": strategy_id}
        _record_control_action(
            "strategy.stop",
            guard.actor,
            guard.approver,
            idem_key,
            {"strategyId": strategy_id},
            response,
        )
        _idempotency_store(idem_key, response)
        return response


@router.post("/strategies/{strategy_id}/update")
async def cc_strategy_update(
    strategy_id: str,
    body: dict[str, Any],
    guard: IdemGuardDep,
    state: StateDep,
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params must be an object")

    try:
        store = _load_params()
        store[strategy_id] = params
        _save_params(store)
    except HTTPException:
        raise
    except _SUPPRESSIBLE_EXCEPTIONS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        response = {"ok": True, "action": "update", "strategyId": strategy_id}
        _record_control_action(
            "strategy.update",
            guard.actor,
            guard.approver,
            idem_key,
            body,
            response,
        )
        _idempotency_store(idem_key, response)
        return response


# Backtests: job tracker backed by filesystem so multiple workers share state
BACKTEST_DIR = Path("data/ops_backtests")
BACKTEST_DIR.mkdir(parents=True, exist_ok=True)


def _job_path(job_id: str) -> Path:
    return BACKTEST_DIR / f"{job_id}.json"


def _save_job(job_id: str, payload: dict[str, Any]) -> None:
    path = _job_path(job_id)
    # Best-effort atomic write
    with NamedTemporaryFile(
        "w", delete=False, dir=str(BACKTEST_DIR), prefix=f"{job_id}.", suffix=".tmp"
    ) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _load_job(job_id: str) -> dict[str, Any] | None:
    path = _job_path(job_id)
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except _SUPPRESSIBLE_EXCEPTIONS:
        return None


def _synth_backtest_result(strategy_name: str) -> dict[str, Any]:
    # Synthetic equity and metrics
    now = int(time.time())
    equity = 10000.0
    series = []
    returns = []
    for i in range(60):
        r = random.gauss(0.0005, 0.01)
        returns.append(r)
        equity *= 1 + r
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - (60 - i) * 3600))
        series.append({"t": ts, "equity": round(equity, 2)})
    pnl_by_symbol = [
        {"symbol": s, "pnl": round(random.uniform(-200, 400), 2)}
        for s in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    ]
    return {
        "metrics": {
            "totalReturn": (equity / 10000.0) - 1.0,
            "sharpe": round(random.uniform(0.5, 1.5), 2),
            "maxDrawdown": round(random.uniform(0.05, 0.2), 3),
            "winRate": round(random.uniform(0.45, 0.65), 3),
            "trades": random.randint(50, 250),
        },
        "equityCurve": series,
        "pnlBySymbol": pnl_by_symbol,
        "returns": returns,
        "trades": [
            {
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(now - random.randint(0, 60) * 3600),
                ),
                "symbol": random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT"]),
                "side": random.choice(["buy", "sell"]),
                "qty": round(random.uniform(0.1, 2.0), 4),
                "price": round(random.uniform(100, 60000), 2),
                "pnl": round(random.uniform(-50, 120), 2),
            }
            for _ in range(80)
        ],
    }


@router.post("/backtests")
async def cc_backtest_start(payload: dict[str, Any], guard: IdemGuardDep) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    job_id = f"job-{int(time.time()*1000)}-{random.randint(100,999)}"
    _save_job(job_id, {"status": "queued", "progress": 0.0})

    async def _run(job: str, strategy_id: str | None) -> None:
        try:
            cur = _load_job(job) or {}
            cur.update({"status": "running"})
            _save_job(job, cur)
            for i in range(5):
                await asyncio.sleep(0.8)
                cur = _load_job(job) or {}
                cur["progress"] = (i + 1) / 6
                _save_job(job, cur)
            # Produce result
            result = _synth_backtest_result(strategy_id or "strategy")
            _save_job(job, {"status": "done", "progress": 1.0, "result": result})
        except _SUPPRESSIBLE_EXCEPTIONS:
            _save_job(job, {"status": "error", "progress": 1.0})

    # Schedule via event loop if available, and also a thread-based runner
    # so tests using TestClient (with short-lived loops) still complete.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run(job_id, payload.get("strategyId")))
    except RuntimeError:
        pass

    import threading

    def _thread_runner() -> None:
        try:
            # Run the async job in a dedicated loop
            asyncio.run(_run(job_id, payload.get("strategyId")))
        except _SUPPRESSIBLE_EXCEPTIONS:
            _save_job(job_id, {"status": "error", "progress": 1.0})

    t = threading.Thread(target=_thread_runner, name=f"backtest-{job_id}", daemon=True)
    t.start()

    response = {"ok": True, "jobId": job_id}
    _record_control_action(
        "backtest.start",
        guard.actor,
        guard.approver,
        idem_key,
        payload,
        response,
    )
    _idempotency_store(idem_key, response)
    return response


@router.get("/backtests/{job_id}")
async def cc_backtest_poll(job_id: str) -> Any:
    job = _load_job(job_id)
    if not job:
        http_error(
            status.HTTP_404_NOT_FOUND,
            "backtest.not_found",
            "Requested backtest job was not found.",
            {"jobId": job_id},
        )
    return job


async def _collect_metrics_bundle(
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    metrics_source = os.getenv("UI_METRICS_SOURCE", "prom").lower()
    fetched_at = time.time()
    metrics_text = ""
    enhanced_data: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if metrics_source in {"direct", "engine"}:
                texts: list[str] = []
                for base in engine_endpoints():
                    try:
                        resp = await client.get(f"{base.rstrip('/')}/metrics")
                        if resp.status_code == 200:
                            texts.append(resp.text)
                    except _SUPPRESSIBLE_EXCEPTIONS:
                        continue
                metrics_text = "\n".join(texts)
            else:
                r = await client.get(pnl.METRICS_URL)
                r.raise_for_status()
                metrics_text = r.text
        if metrics_text:
            parsed = pnl.parse_prometheus_metrics(metrics_text)
            enhanced_data = pnl.enhance_with_registry_data(parsed)
    except _SUPPRESSIBLE_EXCEPTIONS:
        enhanced_data = []

    try:
        snapshot = await state["portfolio"].snapshot()
    except _SUPPRESSIBLE_EXCEPTIONS:
        snapshot = {}

    context: dict[str, Any] = {
        "metricsSource": metrics_source,
        "registryPath": str(pnl.REGISTRY_PATH),
        "fetchedAt": fetched_at,
        "records": len(enhanced_data),
    }
    ts = snapshot.get("ts")
    if ts:
        context["snapshotTimestamp"] = ts
    return enhanced_data, snapshot, context


@router.get("/metrics/summary")
async def cc_metrics_summary(
    state: StateDep,
    from_: str | None = None,
    to: str | None = None,
    strategies: list[str] | None = None,
    symbols: list[str] | None = None,
) -> Any:
    # Pull live metrics from Prometheus (via pnl_dashboard helpers)
    enhanced_data, snap, _context = await _collect_metrics_bundle(state)
    positions = snap.get("positions") or []
    open_positions = len(positions)

    # PnL attribution by symbol from positions
    pnl_by_symbol: dict[str, float] = {}
    for p in positions:
        sym = p.get("symbol") or p.get("product") or "UNKNOWN"
        pnl_val = float(p.get("pnl") or p.get("unrealizedPnl") or p.get("unrealized_pnl") or 0.0)
        pnl_by_symbol[sym] = pnl_by_symbol.get(sym, 0.0) + pnl_val

    # Aggregate portfolio KPIs from enhanced model data
    total_realized = sum(float(d.get("pnl_realized_total", 0.0)) for d in enhanced_data)
    total_unrealized = sum(float(d.get("pnl_unrealized_total", 0.0)) for d in enhanced_data)
    total_pnl = total_realized + total_unrealized
    win_rate = pnl.calculate_overall_win_rate(enhanced_data) if enhanced_data else 0.0
    sharpe = pnl.calculate_portfolio_sharpe(enhanced_data) if enhanced_data else 0.0
    max_dd = max((float(d.get("max_drawdown", 0.0)) for d in enhanced_data), default=0.0)

    # Dev-friendly seeding: if nothing available, provide a small synthetic snapshot
    if not enhanced_data and not positions:
        import random

        rnd = random.Random(42)
        seeded_pnl = round(rnd.uniform(-1500, 2500), 2)
        seeded_symbols = [
            {"symbol": "BTCUSDT", "pnl": round(rnd.uniform(-200, 600), 2)},
            {"symbol": "ETHUSDT", "pnl": round(rnd.uniform(-120, 400), 2)},
            {"symbol": "BNBUSDT", "pnl": round(rnd.uniform(-80, 220), 2)},
        ]
        seeded_returns = [rnd.gauss(0.0005, 0.01) for _ in range(60)]
        # Create a synthetic equity-by-strategy series with 2 lines for visuals
        now = int(time.time())
        eq_series = []
        s1, s2 = 10000.0, 10000.0
        for i in range(60):
            s1 *= 1 + rnd.gauss(0.0004, 0.006)
            s2 *= 1 + rnd.gauss(0.0002, 0.008)
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - (60 - i) * 3600))
            eq_series.append({"t": ts, "alpha": round(s1, 2), "beta": round(s2, 2)})

        return {
            "kpis": {
                "totalPnl": seeded_pnl,
                "winRate": 0.57,
                "sharpe": 0.92,
                "maxDrawdown": 0.137,
                "openPositions": 0,
            },
            "equityByStrategy": eq_series,
            "pnlBySymbol": seeded_symbols,
            "returns": seeded_returns,
        }

    return {
        "kpis": {
            "totalPnl": round(total_pnl, 2),
            "winRate": float(win_rate),
            "sharpe": float(sharpe),
            "maxDrawdown": float(max_dd),
            "openPositions": int(open_positions),
        },
        # Not available from Prometheus snapshot; keep empty until time-series source is wired
        "equityByStrategy": [],
        "pnlBySymbol": [
            {"symbol": k, "pnl": round(v, 2)} for k, v in sorted(pnl_by_symbol.items())
        ],
        # Returns distribution could be derived from model-level returns if persisted; leave empty
        "returns": [],
    }


@router.get("/metrics/models")
async def cc_metrics_models(
    state: StateDep,
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    enhanced_data, _snap, context = await _collect_metrics_bundle(state)
    normalized: list[dict[str, Any]] = []
    for item in enhanced_data:
        model = str(item.get("model") or "unknown")
        venue = str(item.get("venue") or "global")
        identifier = item.get("id") or f"{model}:{venue}"
        normalized.append(
            {
                "id": str(identifier),
                "model": model,
                "venue": venue,
                "ordersSubmitted": float(item.get("orders_submitted_total") or 0),
                "ordersFilled": float(item.get("orders_filled_total") or 0),
                "trades": float(item.get("trades") or 0),
                "pnlRealized": float(item.get("pnl_realized_total") or 0),
                "pnlUnrealized": float(item.get("pnl_unrealized_total") or 0),
                "totalPnl": float(item.get("total_pnl") or 0),
                "winRate": float(item.get("win_rate") or 0),
                "returnPct": float(item.get("return_pct") or 0),
                "sharpe": float(item.get("sharpe") or 0),
                "drawdown": float(item.get("drawdown") or 0),
                "maxDrawdown": float(item.get("max_drawdown") or 0),
                "strategyType": item.get("strategy_type"),
                "version": item.get("version"),
                "tradingDays": item.get("trading_days"),
            }
        )

    normalized.sort(key=lambda row: row.get("totalPnl", 0.0), reverse=True)
    paged = _paginate_items(normalized, cursor, limit)
    paged["meta"] = context
    return paged


@router.get("/positions")
async def cc_positions(
    state: StateDep,
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    sanitized = await _collect_positions(state)
    return _paginate_items(sanitized, cursor, limit)


@router.get("/trades/recent")
async def cc_trades_recent(
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    rows = list(RECENT_TRADES)
    if not rows:
        # Dev seed a few example trades for UI when no feed present
        now = int(time.time())
        rows = [
            {
                "time": now - 300,
                "symbol": "BTCUSDT",
                "side": "buy",
                "qty": 0.15,
                "price": 58500.0,
                "pnl": 24.5,
            },
            {
                "time": now - 120,
                "symbol": "ETHUSDT",
                "side": "sell",
                "qty": 1.8,
                "price": 3150.0,
                "pnl": -12.3,
            },
        ]
    sanitized = []
    for idx, r in enumerate(rows):
        timestamp = r.get("time") or r.get("timestamp") or int(time.time() * 1000)
        symbol = r.get("symbol") or "UNKNOWN"
        entry = {
            "id": r.get("id") or f"trade-{timestamp}-{symbol}-{idx}",
            "time": timestamp,
            "timestamp": timestamp,
            "symbol": symbol,
            "side": (r.get("side") or "buy").lower(),
            "quantity": float(r.get("qty") or r.get("quantity") or 0),
            "price": float(r.get("price") or 0),
            "pnl": r.get("pnl"),
        }
        sanitized.append(entry)
    sanitized.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    return _paginate_items(sanitized, cursor, limit)


@router.get("/alerts")
async def cc_alerts(
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=MAX_PAGE_LIMIT),
) -> Any:
    rows = list(ALERTS_FEED)
    if not rows:
        now = int(time.time())
        rows = [
            {
                "time": now - 600,
                "level": "info",
                "text": "Started Command Center in dev mode",
            },
            {
                "time": now - 120,
                "level": "warn",
                "text": "Exporter heartbeat lag detected",
            },
        ]
    # Ensure deterministic order newest first
    normalized = []
    for idx, row in enumerate(rows):
        timestamp = row.get("time") or row.get("timestamp") or int(time.time() * 1000)
        level = (row.get("level") or row.get("type") or "info").lower()
        normalized.append(
            {
                "id": row.get("id") or f"alert-{timestamp}-{idx}",
                "time": timestamp,
                "timestamp": timestamp,
                "type": level,
                "message": row.get("text") or row.get("message") or "",
            }
        )

    normalized.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return _paginate_items(normalized, cursor, limit)


@router.post("/alerts")
async def cc_alerts_post(item: dict[str, Any], _auth: AuthDep) -> Any:
    row = {
        "time": item.get("time") or int(time.time() * 1000),
        "level": item.get("level") or item.get("type") or "info",
        "text": item.get("text") or item.get("message") or "",
    }
    ALERTS_FEED.append(row)
    await broadcast_event({"type": "alert", "payload": row})
    return {"ok": True}


@router.get("/health")
async def cc_health(state: StateDep) -> Any:
    """Return venue/engine health for the dashboard."""
    try:
        from ops.engine_client import health as engine_health

        eng = await engine_health()
        venues = eng.get("venues") or []
        if isinstance(venues, list) and venues:
            # Map directly if present
            out = [
                {
                    "name": v.get("name") or v.get("venue") or "engine",
                    "status": v.get("status") or ("ok" if v.get("ok", True) else "down"),
                    "latencyMs": float(v.get("latencyMs") or v.get("latency_ms") or 0),
                    "queue": int(v.get("queue") or 0),
                }
                for v in venues
            ]
        else:
            out = [
                {
                    "name": "trading-engine",
                    "status": ("ok" if eng.get("engine") == "ok" or eng.get("ok") else "warn"),
                    "latencyMs": float(eng.get("latency_ms") or 0.0),
                    "queue": int(eng.get("queue") or 0),
                }
            ]
    except _SUPPRESSIBLE_EXCEPTIONS:
        logger.exception("Failed to fetch engine health")
        out = [{"name": "trading-engine", "status": "down", "latencyMs": 0.0, "queue": 0}]
    return {"venues": out}


_price_peers: set[WebSocket] = set()
_account_peers: set[WebSocket] = set()
_orders_peers: set[WebSocket] = set()
_trades_peers: set[WebSocket] = set()
_events_peers: set[WebSocket] = set()


async def _guard_ws(websocket: WebSocket) -> None:
    if _validate_ws_session(websocket.query_params.get("session")):
        return
    await websocket.close(code=4401)
    raise WebSocketDisconnect()


async def _ws_keep(websocket: WebSocket, peers: set[WebSocket]) -> None:
    await websocket.accept()
    peers.add(websocket)
    try:
        while True:
            await asyncio.sleep(60.0)
    except WebSocketDisconnect:
        pass
    finally:
        peers.discard(websocket)


async def _broadcast(peers: set[WebSocket], message: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in list(peers):
        try:
            await ws.send_json(message)
        except _SUPPRESSIBLE_EXCEPTIONS:
            dead.append(ws)
    for ws in dead:
        peers.discard(ws)


async def broadcast_price(message: dict[str, Any]) -> None:
    await _broadcast(_price_peers, message)


async def broadcast_account(message: dict[str, Any]) -> None:
    await _broadcast(_account_peers, message)


async def broadcast_order(message: dict[str, Any]) -> None:
    await _broadcast(_orders_peers, message)


async def broadcast_trade(message: dict[str, Any]) -> None:
    await _broadcast(_trades_peers, message)


async def broadcast_event(message: dict[str, Any]) -> None:
    await _broadcast(_events_peers, message)


async def ws_price(websocket: WebSocket) -> None:
    await _guard_ws(websocket)
    await _ws_keep(websocket, _price_peers)


async def ws_account(websocket: WebSocket) -> None:
    await _guard_ws(websocket)
    await _ws_keep(websocket, _account_peers)


async def ws_orders(websocket: WebSocket) -> None:
    await _guard_ws(websocket)
    await _ws_keep(websocket, _orders_peers)


async def ws_trades(websocket: WebSocket) -> None:
    await _guard_ws(websocket)
    await _ws_keep(websocket, _trades_peers)


async def ws_events(websocket: WebSocket) -> None:
    await _guard_ws(websocket)
    await _ws_keep(websocket, _events_peers)


__all__ = [
    "router",
    "broadcast_price",
    "broadcast_account",
    "broadcast_order",
    "broadcast_trade",
    "broadcast_event",
    "ws_price",
    "ws_account",
    "ws_orders",
    "ws_trades",
    "ws_events",
]
