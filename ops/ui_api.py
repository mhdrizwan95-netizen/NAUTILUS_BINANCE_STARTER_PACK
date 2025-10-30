"""FastAPI router exposing the Command Center surface."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from ops import ui_state

OPS_TOKEN = os.getenv("OPS_API_TOKEN", "dev-token")
WS_TOKEN = OPS_TOKEN

router = APIRouter(prefix="/api", tags=["command-center"])


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


def require_ops_token(x_ops_token: Optional[str] = Header(None)) -> None:
    if x_ops_token != OPS_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def get_state() -> Dict[str, Any]:
    return ui_state.get_services()


@router.get("/engine/status")
async def engine_status(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["ops"].status()


@router.get("/config/effective")
async def config_effective(state: Dict[str, Any] = Depends(get_state)) -> Any:
    return await state["config"].get_effective()


@router.put("/config")
async def config_update(
    patch: ConfigPatch,
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    payload = {k: v for k, v in patch.dict().items() if v is not None}
    if not payload:
        return await state["config"].get_effective()
    return await state["config"].patch(payload)


@router.get("/strategies")
async def strategies_list(state: Dict[str, Any] = Depends(get_state)) -> Any:
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
async def universe_get(strategy_id: str, state: Dict[str, Any] = Depends(get_state)) -> Any:
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
    payload: Dict[str, Any],
    state: Dict[str, Any] = Depends(get_state),
    _auth: None = Depends(require_ops_token),
) -> Any:
    enabled = bool(payload.get("enabled", True))
    return await state["ops"].set_trading_enabled(enabled)


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
    return await state["ops"].transfer_internal(body.asset, body.amount, body.source, body.target)


@router.post("/events/trade")
async def post_trade_event(
    item: Dict[str, Any],
    _auth: None = Depends(require_ops_token),
) -> Any:
    await broadcast_trade(item)
    await broadcast_event({"type": "trade", "payload": item})
    return {"ok": True}


_price_peers: Set[WebSocket] = set()
_account_peers: Set[WebSocket] = set()
_orders_peers: Set[WebSocket] = set()
_trades_peers: Set[WebSocket] = set()
_events_peers: Set[WebSocket] = set()


async def _guard_ws(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token != WS_TOKEN:
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
