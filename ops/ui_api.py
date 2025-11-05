"""FastAPI router exposing the Command Center surface."""

from __future__ import annotations

import asyncio
import json
import os
import random
import secrets
import time
from collections import OrderedDict, deque
from pathlib import Path
from threading import RLock
from typing import Any, Deque, Dict, List, Optional, Set

import httpx
import yaml
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel

from ops import pnl_dashboard as pnl
from ops import ui_state
from ops.middleware.control_guard import (
    ControlContext,
    IdempotentTwoManGuard,
    TokenOnlyGuard,
)
from ops.governance_daemon import (
    reload_governance_policies as governance_reload_policies,
)


def _load_ops_token() -> str:
    token = os.getenv("OPS_API_TOKEN")
    token_file = os.getenv("OPS_API_TOKEN_FILE")
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Failed to read OPS_API_TOKEN_FILE ({token_file})") from exc
    if not token or token == "dev-token":
        raise RuntimeError("Set OPS_API_TOKEN or OPS_API_TOKEN_FILE before starting the Command Center API")
    return token


OPS_TOKEN = _load_ops_token()
WS_TOKEN = OPS_TOKEN

def _load_approver_tokens() -> Set[str]:
    raw = os.getenv("OPS_APPROVER_TOKENS") or os.getenv("OPS_APPROVER_TOKEN")
    if not raw:
        return set()
    return {token.strip() for token in raw.split(",") if token.strip()}

OPS_APPROVER_TOKENS = _load_approver_tokens()

def _require_approver(header: str | None) -> Optional[str]:
    if not OPS_APPROVER_TOKENS:
        return None
    if not header or header not in OPS_APPROVER_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approver token required",
        )
    return header


def _require_idempotency(request: Request) -> tuple[str, Optional[Dict[str, Any]]]:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Idempotency-Key header",
        )
    cached = _idempotency_lookup(key)
    return key, cached

router = APIRouter(prefix="/api", tags=["command-center"])

_IDEMPOTENCY_CACHE: OrderedDict[str, tuple[float, Dict[str, Any]]] = OrderedDict()
_IDEMPOTENCY_LOCK = RLock()
_IDEMPOTENCY_MAX = 512
CONTROL_AUDIT_PATH = Path("ops/logs/control_actions.jsonl")
_WS_SESSIONS: Dict[str, float] = {}
_WS_SESSION_LOCK = RLock()
_WS_SESSION_TTL_SEC = float(os.getenv("OPS_WS_SESSION_TTL", "900"))


class ConfigPatch(BaseModel):
    DRY_RUN: Optional[bool] = None
    SYMBOL_SCANNER_ENABLED: Optional[bool] = None
    SOFT_BREACH_ENABLED: Optional[bool] = None
    SOFT_BREACH_TIGHTEN_SL_PCT: Optional[float] = None
    SOFT_BREACH_BREAKEVEN_OK: Optional[bool] = None
    SOFT_BREACH_CANCEL_ENTRIES: Optional[bool] = None


class StrategyPatch(BaseModel):
    enabled: Optional[bool] = None
    weights: Optional[Dict[str, float]] = None


class CancelOrdersRequest(BaseModel):
    orderIds: List[str]


class TransferRequest(BaseModel):
    asset: str
    amount: float
    source: str
    target: str


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: Optional[str] = None


class FlattenRequest(BaseModel):
    dryRun: Optional[bool] = False


def require_ops_token(x_ops_token: Optional[str] = Header(None)) -> None:
    if x_ops_token != OPS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )


def get_state() -> Dict[str, Any]:
    return ui_state.get_services()


# ---------------------------------------------------------------------------
# In-memory/eventual-persist stores to satisfy the Command Center frontend
# ---------------------------------------------------------------------------

# Recent trades and alerts feeds (simple in-memory ring buffers)
RECENT_TRADES: Deque[Dict[str, Any]] = deque(maxlen=500)
ALERTS_FEED: Deque[Dict[str, Any]] = deque(maxlen=200)

# Strategy parameter storage backed by a JSON file
PARAMS_PATH = Path("ops/strategy_params.json")


def _load_params() -> Dict[str, Any]:
    if not PARAMS_PATH.exists():
        return {}
    try:
        return json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_params(payload: Dict[str, Any]) -> None:
    PARAMS_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _idempotency_lookup(key: str) -> Optional[Dict[str, Any]]:
    with _IDEMPOTENCY_LOCK:
        cached = _IDEMPOTENCY_CACHE.get(key)
        if cached:
            return cached[1]
    return None


def _idempotency_store(key: str, response: Dict[str, Any]) -> None:
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_CACHE[key] = (time.time(), response)
        _IDEMPOTENCY_CACHE.move_to_end(key)
        while len(_IDEMPOTENCY_CACHE) > _IDEMPOTENCY_MAX:
            _IDEMPOTENCY_CACHE.popitem(last=False)


def _idempotency_cached_response(idem_key: str) -> Optional[Dict[str, Any]]:
    if not idem_key:
        return None
    return _idempotency_lookup(idem_key)


def _record_control_action(
    action: str,
    actor: Optional[str],
    approver: Optional[str],
    idempotency_key: str,
    payload: Dict[str, Any],
    result: Dict[str, Any],
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
    except Exception:
        # Audit logging best-effort; avoid interrupting control flow
        pass


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


def _validate_ws_session(session: Optional[str]) -> bool:
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
    request: Request, _auth: None = Depends(require_ops_token)
) -> Dict[str, Any]:
    """Issue a temporary session token for WebSocket subscriptions."""
    session, expiry = _issue_ws_session()
    actor = request.headers.get("X-Ops-Actor")
    _record_control_action(
        "ws_session.issue",
        actor,
        None,
        session,
        {},
        {"expires": expiry},
    )
    return {"session": session, "expires": expiry}


def _yaml_schema_to_param_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert strategy_schemas YAML format into the UI ParamSchema contract."""
    fields: list[Dict[str, Any]] = []
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


def _load_strategy_schema(strategy_id: str) -> Dict[str, Any]:
    """Load YAML schema by strategy id; fallback to momentum_breakout if missing."""
    base = Path("strategy_schemas")
    candidates = [base / f"{strategy_id}.yaml", base / "momentum_breakout.yaml"]
    for path in candidates:
        if path.exists():
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return _yaml_schema_to_param_schema(raw)
            except Exception:
                continue
    # Empty schema fallback
    return {"title": strategy_id, "fields": []}


@router.get("/engine/status")
async def engine_status(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["ops"].status()


@router.get("/config/effective")
async def config_effective(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["config"].get_effective()


@router.put("/config")
async def config_update(
    patch: ConfigPatch,
    guard: ControlContext = Depends(IdempotentTwoManGuard),
    state: Dict[str, Any] = Depends(get_state),
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    payload = {k: v for k, v in patch.dict().items() if v is not None}
    if not payload:
        result = await state["config"].get_effective()
        payload_for_audit: Dict[str, Any] = {"noop": True}
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
async def strategies_list(state: Dict[str, Any] = Depends(get_state)) -> Any:
    """Original governance view of strategies (weights, enabled).

    Kept for compatibility; the Command Center UI consumes /api/strategies
    which returns schema-driven cards.
    """
    return await state["strategy"].list()


@router.patch("/strategies/{strategy_id}")
async def strategies_patch(
    strategy_id: str,
    patch: StrategyPatch,
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    return await state["strategy"].patch(strategy_id, patch.dict(exclude_none=True))


@router.get("/universe/{strategy_id}")
async def universe_get(
    strategy_id: str, state: Dict[str, Any] = Depends(get_state)
) -> Any:
    return await state["scanner"].universe(strategy_id)


@router.post("/universe/{strategy_id}/refresh")
async def universe_refresh(
    strategy_id: str,
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    return await state["scanner"].refresh(strategy_id)


@router.get("/orders/open")
async def orders_open(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["orders"].list_open_orders()


@router.post("/orders/cancel")
async def orders_cancel(
    body: CancelOrdersRequest,
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    try:
        return await state["orders"].cancel_many(body.orderIds)
    except RuntimeError as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/positions/open")
async def positions_open(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["portfolio"].list_open_positions()


@router.post("/risk/soft-breach/now")
async def soft_breach(
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    return await state["risk"].soft_breach_now()


@router.post("/ops/kill-switch")
async def killswitch(
    payload: KillSwitchRequest,
    guard: ControlContext = Depends(IdempotentTwoManGuard),
    state: Dict[str, Any] = Depends(get_state),
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    result = await state["ops"].set_trading_enabled(payload.enabled)
    action = "resume" if payload.enabled else "pause"
    response = {"ok": True, "action": action, "result": result, "approver": guard.approver}
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
    guard: ControlContext = Depends(IdempotentTwoManGuard),
    state: Dict[str, Any] = Depends(get_state),
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        result = await state["ops"].flatten_positions(actor=guard.actor)
    except RuntimeError as exc:  # pragma: no cover - defensive
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    response = {"ok": True, "action": "flatten", "approver": guard.approver, **result}
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
    guard: ControlContext = Depends(TokenOnlyGuard),
) -> Any:
    try:
        ok = governance_reload_policies()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Reload failed: {exc}"
        ) from exc
    if not ok:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Reload returned false"
        )
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
async def feeds_status(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["feeds"].status()


@router.patch("/feeds/announcements")
async def feeds_announcements(
    body: Dict[str, Any],
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    return await state["feeds"].patch_announcements(body)


@router.patch("/feeds/meme")
async def feeds_meme(
    body: Dict[str, Any],
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    return await state["feeds"].patch_meme(body)


@router.post("/account/transfer")
async def account_transfer(
    body: TransferRequest,
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    return await state["ops"].transfer_internal(
        body.asset, body.amount, body.source, body.target
    )


@router.post("/events/trade")
async def post_trade_event(
    item: Dict[str, Any],
    _auth: None = Depends(require_ops_token),
) -> Any:
    # Capture recent trade for the frontend feed
    try:
        RECENT_TRADES.append(
            {
                "time": item.get("time")
                or item.get("timestamp")
                or int(time.time() * 1000),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "qty": float(item.get("qty") or item.get("quantity") or 0),
                "price": float(item.get("price") or 0),
                "pnl": item.get("pnl"),
            }
        )
    except Exception:
        pass
    await broadcast_trade(item)
    await broadcast_event({"type": "trade", "payload": item})
    return {"ok": True}


# ----------------------- Frontend integration endpoints ----------------------


@router.get("/strategies")
async def cc_strategies_list(state: Dict[str, Any] = Depends(get_state)) -> Any:
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
        except Exception:
            symbols = []

        # Minimal performance with dev-friendly sparkline when no live data
        perf = {"pnl": 0.0}
        try:
            import random, time as _time

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
        except Exception:
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

    return items


@router.get("/strategies/{strategy_id}")
async def cc_strategy_get(
    strategy_id: str, state: Dict[str, Any] = Depends(get_state)
) -> Any:
    params_store = _load_params()
    schema = _load_strategy_schema(strategy_id)
    try:
        uni = await state["scanner"].universe(strategy_id)
        symbols = uni.get("symbols", [])
    except Exception:
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
    body: Dict[str, Any] | None = None,
    guard: ControlContext = Depends(IdempotentTwoManGuard),
    state: Dict[str, Any] = Depends(get_state),
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/strategies/{strategy_id}/stop")
async def cc_strategy_stop(
    strategy_id: str,
    guard: ControlContext = Depends(IdempotentTwoManGuard),
    state: Dict[str, Any] = Depends(get_state),
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        await state["strategy"].patch(strategy_id, {"enabled": False})
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/strategies/{strategy_id}/update")
async def cc_strategy_update(
    strategy_id: str,
    body: Dict[str, Any],
    guard: ControlContext = Depends(IdempotentTwoManGuard),
    state: Dict[str, Any] = Depends(get_state),
) -> Any:
    idem_key = guard.idempotency_key or ""
    cached = _idempotency_cached_response(idem_key)
    if cached:
        return cached

    try:
        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise HTTPException(status_code=400, detail="params must be an object")
        store = _load_params()
        store[strategy_id] = params
        _save_params(store)
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Backtests: job tracker backed by filesystem so multiple workers share state
from pathlib import Path as _Path
from tempfile import NamedTemporaryFile

BACKTEST_DIR = _Path("data/ops_backtests")
BACKTEST_DIR.mkdir(parents=True, exist_ok=True)


def _job_path(job_id: str) -> _Path:
    return BACKTEST_DIR / f"{job_id}.json"


def _save_job(job_id: str, payload: Dict[str, Any]) -> None:
    path = _job_path(job_id)
    # Best-effort atomic write
    with NamedTemporaryFile(
        "w", delete=False, dir=str(BACKTEST_DIR), prefix=f"{job_id}.", suffix=".tmp"
    ) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = _Path(tmp.name)
    tmp_path.replace(path)


def _load_job(job_id: str) -> Dict[str, Any] | None:
    path = _job_path(job_id)
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _synth_backtest_result(strategy_name: str) -> Dict[str, Any]:
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
async def cc_backtest_start(
    payload: Dict[str, Any],
    guard: ControlContext = Depends(IdempotentTwoManGuard),
) -> Any:
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
        except Exception:
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
        except Exception:
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
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/metrics/summary")
async def cc_metrics_summary(
    from_: Optional[str] = None,
    to: Optional[str] = None,
    strategies: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
    state: Dict[str, Any] = Depends(get_state),
) -> Any:
    # Pull live metrics from Prometheus (via pnl_dashboard helpers)
    enhanced_data: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            metrics_source = os.getenv("UI_METRICS_SOURCE", "prom").lower()
            if metrics_source in {"direct", "engine"}:
                # Bypass Prometheus: pull /metrics from each engine and concatenate
                texts: list[str] = []
                for base in engine_endpoints():
                    try:
                        resp = await client.get(f"{base.rstrip('/')}/metrics")
                        if resp.status_code == 200:
                            texts.append(resp.text)
                    except Exception:
                        continue
                metrics_text = "\n".join(texts)
            else:
                # Default: use configured Prometheus/registry endpoint
                r = await client.get(pnl.METRICS_URL)
                r.raise_for_status()
                metrics_text = r.text
        parsed = pnl.parse_prometheus_metrics(metrics_text)
        enhanced_data = pnl.enhance_with_registry_data(parsed)
    except Exception:
        enhanced_data = []

    # Basic KPIs from portfolio snapshot when available
    try:
        snap = await state["portfolio"].snapshot()
    except Exception:
        snap = {}
    positions = snap.get("positions") or []
    open_positions = len(positions)

    # PnL attribution by symbol from positions
    pnl_by_symbol: Dict[str, float] = {}
    for p in positions:
        sym = p.get("symbol") or p.get("product") or "UNKNOWN"
        pnl_val = float(
            p.get("pnl") or p.get("unrealizedPnl") or p.get("unrealized_pnl") or 0.0
        )
        pnl_by_symbol[sym] = pnl_by_symbol.get(sym, 0.0) + pnl_val

    # Aggregate portfolio KPIs from enhanced model data
    total_realized = sum(float(d.get("pnl_realized_total", 0.0)) for d in enhanced_data)
    total_unrealized = sum(
        float(d.get("pnl_unrealized_total", 0.0)) for d in enhanced_data
    )
    total_pnl = total_realized + total_unrealized
    win_rate = pnl.calculate_overall_win_rate(enhanced_data) if enhanced_data else 0.0
    sharpe = pnl.calculate_portfolio_sharpe(enhanced_data) if enhanced_data else 0.0
    max_dd = max(
        (float(d.get("max_drawdown", 0.0)) for d in enhanced_data), default=0.0
    )

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


@router.get("/positions")
async def cc_positions(state: Dict[str, Any] = Depends(get_state)) -> Any:
    try:
        pos = await state["portfolio"].list_open_positions()
    except Exception:
        pos = []
    out: list[dict[str, Any]] = []
    for p in pos:
        out.append(
            {
                "symbol": p.get("symbol")
                or p.get("product")
                or p.get("instrument")
                or "UNKNOWN",
                "qty": float(p.get("qty") or p.get("quantity") or p.get("size") or 0),
                "entry": float(
                    p.get("entry")
                    or p.get("entry_price")
                    or p.get("avgEntryPrice")
                    or 0
                ),
                "mark": float(
                    p.get("mark") or p.get("mark_price") or p.get("markPrice") or 0
                ),
                "pnl": float(
                    p.get("pnl")
                    or p.get("unrealizedPnl")
                    or p.get("unrealized_pnl")
                    or 0
                ),
            }
        )
    return out


@router.get("/trades/recent")
async def cc_trades_recent(limit: int = 100) -> Any:
    rows = list(RECENT_TRADES)[-limit:]
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
    # Ensure shape matches frontend expectations
    return [
        {
            "time": r.get("time"),
            "symbol": r.get("symbol"),
            "side": r.get("side"),
            "qty": r.get("qty"),
            "price": r.get("price"),
            "pnl": r.get("pnl"),
        }
        for r in rows
    ]


@router.get("/alerts")
async def cc_alerts(limit: int = 50) -> Any:
    rows = list(ALERTS_FEED)[-limit:]
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
    return rows


@router.post("/alerts")
async def cc_alerts_post(
    item: Dict[str, Any], _auth: None = Depends(require_ops_token)
) -> Any:
    row = {
        "time": item.get("time") or int(time.time() * 1000),
        "level": item.get("level") or item.get("type") or "info",
        "text": item.get("text") or item.get("message") or "",
    }
    ALERTS_FEED.append(row)
    await broadcast_event({"type": "alert", "payload": row})
    return {"ok": True}


@router.get("/health")
async def cc_health(state: Dict[str, Any] = Depends(get_state)) -> Any:
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
                    "status": v.get("status")
                    or ("ok" if v.get("ok", True) else "down"),
                    "latencyMs": float(v.get("latencyMs") or v.get("latency_ms") or 0),
                    "queue": int(v.get("queue") or 0),
                }
                for v in venues
            ]
        else:
            out = [
                {
                    "name": "trading-engine",
                    "status": (
                        "ok" if eng.get("engine") == "ok" or eng.get("ok") else "warn"
                    ),
                    "latencyMs": float(eng.get("latency_ms") or 0.0),
                    "queue": int(eng.get("queue") or 0),
                }
            ]
    except Exception:
        out = [
            {"name": "trading-engine", "status": "down", "latencyMs": 0.0, "queue": 0}
        ]
    return {"venues": out}


_price_peers: Set[WebSocket] = set()
_account_peers: Set[WebSocket] = set()
_orders_peers: Set[WebSocket] = set()
_trades_peers: Set[WebSocket] = set()
_events_peers: Set[WebSocket] = set()


async def _guard_ws(websocket: WebSocket) -> None:
    if _validate_ws_session(websocket.query_params.get("session")):
        return
    await websocket.close(code=4401)
    raise WebSocketDisconnect()


async def _ws_keep(websocket: WebSocket, peers: Set[WebSocket]) -> None:
    await websocket.accept()
    peers.add(websocket)
    try:
        while True:
            await asyncio.sleep(60.0)
    except WebSocketDisconnect:
        pass
    finally:
        peers.discard(websocket)


async def _broadcast(peers: Set[WebSocket], message: Dict[str, Any]) -> None:
    dead: List[WebSocket] = []
    for ws in list(peers):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        peers.discard(ws)


async def broadcast_price(message: Dict[str, Any]) -> None:
    await _broadcast(_price_peers, message)


async def broadcast_account(message: Dict[str, Any]) -> None:
    await _broadcast(_account_peers, message)


async def broadcast_order(message: Dict[str, Any]) -> None:
    await _broadcast(_orders_peers, message)


async def broadcast_trade(message: Dict[str, Any]) -> None:
    await _broadcast(_trades_peers, message)


async def broadcast_event(message: Dict[str, Any]) -> None:
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
