from __future__ import annotations

import asyncio
import json
import math
import os
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Nautilus Deck API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE: Dict[str, Any] = {
    "mode": "yellow",
    "kill": False,
    "strategies": {
        "scalp": {"enabled": True, "risk_share": 0.25},
        "momentum": {"enabled": True, "risk_share": 0.35},
        "trend": {"enabled": True, "risk_share": 0.25},
        "event": {"enabled": True, "risk_share": 0.15},
    },
    "universe_weights": {
        "liquidity": 0.25,
        "volatility": 0.20,
        "velocity": 0.25,
        "spread": 0.10,
        "funding": 0.05,
        "event_heat": 0.15,
    },
    "metrics": {
        "equity_usd": 2000.0,
        "open_positions": 0,
        "open_risk_sum_pct": 0.0,
        "pnl_24h": 0.0,
        "drawdown_pct": 0.0,
        "tick_to_order_ms_p50": 50.0,
        "tick_to_order_ms_p95": 95.0,
        "venue_error_rate_pct": 0.0,
        "breaker": {"equity": False, "venue": False},
    },
    "pnl_by_strategy": {},
    "top_symbols": [],
}

STATE_LOCK = asyncio.Lock()
CLIENTS: Set[WebSocket] = set()
TRADES: List[Dict[str, Any]] = []
_MAX_TRADE_BUFFER = 400
_LAT_SAMPLE_SIZE = 200

_METRIC_ALIASES = {
    "tick_p50_ms": "tick_to_order_ms_p50",
    "tick_p95_ms": "tick_to_order_ms_p95",
    "error_rate_pct": "venue_error_rate_pct",
}
_INT_METRICS = {"open_positions"}


class ModeIn(BaseModel):
    mode: str


class ToggleIn(BaseModel):
    enabled: bool


class RiskShareIn(BaseModel):
    strategy: str
    risk_share: float = Field(ge=0.0, le=1.0)


class UniverseWeightsIn(BaseModel):
    liquidity: float
    volatility: float
    velocity: float
    spread: float
    funding: float
    event_heat: float


class MetricsUpdateIn(BaseModel):
    equity_usd: Optional[float] = None
    open_positions: Optional[int] = None
    open_risk_sum_pct: Optional[float] = None
    pnl_24h: Optional[float] = None
    drawdown_pct: Optional[float] = None
    tick_to_order_ms_p50: Optional[float] = None
    tick_to_order_ms_p95: Optional[float] = None
    venue_error_rate_pct: Optional[float] = None
    breaker_equity: Optional[bool] = None
    breaker_venue: Optional[bool] = None


class MetricsPushIn(BaseModel):
    metrics: Optional[Dict[str, Any]] = None
    pnl_by_strategy: Optional[Dict[str, Any]] = None


class StrategyStateIn(BaseModel):
    enabled: Optional[bool] = None
    risk_share: Optional[float] = None


class TopSymbol(BaseModel):
    symbol: str
    score: float
    velocity: Optional[float] = 0.0
    event_heat: Optional[float] = 0.0


class TopSymbolsIn(BaseModel):
    symbols: List[TopSymbol]


class TradeIn(BaseModel):
    ts: float = Field(default_factory=lambda: time.time())
    strategy: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    pnl_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    info: Optional[Dict[str, Any]] = None


def _copy_state() -> Dict[str, Any]:
    return json.loads(json.dumps(STATE))


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(ordered[lower])
    frac = pos - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * frac)


async def broadcast(msg: Dict[str, Any]) -> None:
    data = json.dumps(msg)
    dead: List[WebSocket] = []
    for ws in list(CLIENTS):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for sock in dead:
        CLIENTS.discard(sock)


def _merge_metrics(state_metrics: Dict[str, Any], updates: Dict[str, Any]) -> bool:
    changed = False
    for raw_key, value in updates.items():
        key = _METRIC_ALIASES.get(raw_key, raw_key)
        if key == "breaker" and isinstance(value, dict):
            breaker = state_metrics.setdefault("breaker", {"equity": False, "venue": False})
            for field in ("equity", "venue"):
                if field in value and breaker.get(field) != bool(value[field]):
                    breaker[field] = bool(value[field])
                    changed = True
            continue
        if value is None:
            continue
        if key in _INT_METRICS:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
        else:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
        if state_metrics.get(key) != parsed:
            state_metrics[key] = parsed
            changed = True
    return changed


@app.get("/status")
async def status() -> JSONResponse:
    async with STATE_LOCK:
        snapshot = _copy_state()
    return JSONResponse(snapshot)


@app.post("/risk/mode")
async def set_mode(payload: ModeIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        STATE["mode"] = payload.mode
    await broadcast({"type": "mode", "mode": payload.mode})
    return {"ok": True}


@app.post("/kill")
async def kill(toggle: ToggleIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        STATE["kill"] = toggle.enabled
    await broadcast({"type": "kill", "enabled": toggle.enabled})
    return {"ok": True}


@app.post("/allocator/weights")
async def set_weights(body: RiskShareIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        strategies = STATE["strategies"]
        if body.strategy not in strategies:
            raise HTTPException(status_code=404, detail=f"Unknown strategy '{body.strategy}'")
        strategies[body.strategy]["risk_share"] = float(body.risk_share)
        payload = {
            "type": "weights",
            "strategy": body.strategy,
            "risk_share": strategies[body.strategy]["risk_share"],
        }
    await broadcast(payload)
    return {"ok": True, "strategy": payload}


@app.post("/universe/weights")
async def set_universe(body: UniverseWeightsIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        STATE["universe_weights"] = body.model_dump()
        payload = {"type": "universe_weights", **STATE["universe_weights"]}
    await broadcast(payload)
    return {"ok": True}


@app.post("/strategies/{strategy}")
async def update_strategy(strategy: str, body: StrategyStateIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        strategies = STATE["strategies"]
        if strategy not in strategies:
            raise HTTPException(status_code=404, detail=f"Unknown strategy '{strategy}'")
        strat_state = strategies[strategy]
        if body.enabled is not None:
            strat_state["enabled"] = bool(body.enabled)
        if body.risk_share is not None:
            strat_state["risk_share"] = float(max(0.0, min(1.0, body.risk_share)))
        payload = {"type": "strategy", "strategy": strategy, **strat_state}
    await broadcast(payload)
    return {"ok": True, "strategy": payload}


@app.post("/metrics")
async def update_metrics(metrics: MetricsUpdateIn) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for field in (
        "equity_usd",
        "open_positions",
        "open_risk_sum_pct",
        "pnl_24h",
        "drawdown_pct",
        "tick_to_order_ms_p50",
        "tick_to_order_ms_p95",
        "venue_error_rate_pct",
    ):
        value = getattr(metrics, field)
        if value is not None:
            updates[field] = value
    breaker: Dict[str, Any] = {}
    if metrics.breaker_equity is not None:
        breaker["equity"] = metrics.breaker_equity
    if metrics.breaker_venue is not None:
        breaker["venue"] = metrics.breaker_venue
    if breaker:
        updates["breaker"] = breaker

    async with STATE_LOCK:
        state_metrics = STATE.setdefault("metrics", {})
        changed = _merge_metrics(state_metrics, updates)
        payload = {
            "type": "metrics",
            "metrics": dict(state_metrics),
            "pnl_by_strategy": dict(STATE.get("pnl_by_strategy", {})),
        }
    if changed:
        await broadcast(payload)
    return {"ok": True, "changed": changed}


@app.post("/metrics/push")
async def metrics_push(body: MetricsPushIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        changed = False
        state_metrics = STATE.setdefault("metrics", {})
        if body.metrics:
            changed |= _merge_metrics(state_metrics, body.metrics)
        if body.pnl_by_strategy:
            cleaned: Dict[str, float] = {}
            for strat, value in body.pnl_by_strategy.items():
                try:
                    cleaned[strat] = float(value)
                except (TypeError, ValueError):
                    continue
            if cleaned and cleaned != STATE.get("pnl_by_strategy", {}):
                STATE["pnl_by_strategy"] = cleaned
                changed = True
        payload = {
            "type": "metrics",
            "metrics": dict(state_metrics),
            "pnl_by_strategy": dict(STATE.get("pnl_by_strategy", {})),
        }
    if changed:
        await broadcast(payload)
    return {"ok": True, "changed": changed}


@app.post("/top")
async def update_top_symbols(body: TopSymbolsIn) -> Dict[str, Any]:
    async with STATE_LOCK:
        STATE["top_symbols"] = [entry.model_dump() for entry in body.symbols]
        payload = {"type": "top", "symbols": list(STATE["top_symbols"])}
    await broadcast(payload)
    return {"ok": True, "count": len(body.symbols)}


@app.post("/trades")
async def ingest_trade(body: TradeIn) -> Dict[str, Any]:
    metrics_payload: Optional[Dict[str, Any]] = None
    async with STATE_LOCK:
        trade = body.model_dump()
        TRADES.append(trade)
        if len(TRADES) > _MAX_TRADE_BUFFER:
            del TRADES[: len(TRADES) - _MAX_TRADE_BUFFER]
        latencies = [
            float(t["latency_ms"])
            for t in TRADES[-_LAT_SAMPLE_SIZE:]
            if isinstance(t.get("latency_ms"), (int, float))
        ]
        if latencies:
            p50 = _quantile(latencies, 0.5)
            p95 = _quantile(latencies, 0.95)
            metrics = STATE.setdefault("metrics", {})
            metrics["tick_to_order_ms_p50"] = p50
            metrics["tick_to_order_ms_p95"] = p95
            metrics_payload = {
                "type": "metrics",
                "metrics": dict(metrics),
                "pnl_by_strategy": dict(STATE.get("pnl_by_strategy", {})),
            }
    await broadcast({"type": "trade", "trade": body.model_dump()})
    if metrics_payload:
        await broadcast(metrics_payload)
    return {"ok": True}


@app.websocket("/ws")
async def ws(ws: WebSocket) -> None:
    await ws.accept()
    CLIENTS.add(ws)
    async with STATE_LOCK:
        snapshot = {"type": "snapshot", **STATE}
    await ws.send_text(json.dumps(snapshot))
    try:
        while True:
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        CLIENTS.discard(ws)


static_dir = os.environ.get("DECK_STATIC_DIR", "./deck")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="deck")
