
import os
import json
import logging
import asyncio
import redis.asyncio as redis
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import secrets

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ops.server")

APP = FastAPI(title="Nautilus Phase 8 Gateway", version="0.8.0")

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")

# Redis Client Manager
redis_client: Optional[redis.Redis] = None

@APP.on_event("startup")
async def startup():
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"Connected to Redis at {REDIS_URL}")

@APP.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()

# --- Pydantic Models ---

class OptimizationRequest(BaseModel):
    strategy_template: str
    param_ranges: Dict[str, Any]
    max_evals: int = 50

class CommandRequest(BaseModel):
    cmd: str
    params: Dict[str, Any] = {}

# --- Smart Ingestor ---

@APP.post("/upload")
async def upload_csv(file: UploadFile):
    """
    Phase 8 Smart Ingestor.
    Detects CSV columns, converts to Parquet, registers in Catalog.
    """
    try:
        # Save temp file
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Smart Detection with Pandas
        df = pd.read_csv(temp_path)
        
        # Normalize Columns (Heuristic)
        col_map = {}
        for col in df.columns:
            c = col.lower()
            if "open" in c: col_map[col] = "open"
            elif "high" in c: col_map[col] = "high"
            elif "low" in c: col_map[col] = "low"
            elif "close" in c: col_map[col] = "close"
            elif "vol" in c: col_map[col] = "volume"
            elif "time" in c or "date" in c: col_map[col] = "timestamp"

        df.rename(columns=col_map, inplace=True)
        
        # Validation
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            return JSONResponse(status_code=400, content={"error": f"Missing columns. Found: {df.columns.tolist()}"})
        
        # Convert to Parquet
        parquet_filename = f"{os.path.splitext(file.filename)[0]}.parquet"
        output_path = os.path.join(DATA_DIR, "catalog", parquet_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        df.to_parquet(output_path)
        
        logger.info(f"SmartIngestor: Converted {file.filename} to {output_path}")
        
        return {"status": "ok", "path": output_path, "rows": len(df)}

    except Exception as e:
        logger.error(f"Ingestion Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Optimization Dispatch ---

@APP.post("/optimize")
async def dispatch_optimization(request: OptimizationRequest):
    """
    Dispatches a Hyperopt Job to the Redis Queue.
    """
    job_id = secrets.token_hex(8)
    job_payload = {
        "id": job_id,
        "strategy": request.strategy_template,
        "param_ranges": request.param_ranges,
        "max_evals": request.max_evals
    }
    
    await redis_client.rpush("nautilus:jobs", json.dumps(job_payload))
    logger.info(f"Dispatched Optimization Job {job_id}")
    
    return {"status": "dispatched", "job_id": job_id}

# --- Command Proxy ---

@APP.post("/command")
async def send_command(request: CommandRequest):
    """
    Proxies JSON-RPC commands to the Trading Engine via Redis.
    """
    payload = request.dict()
    await redis_client.publish("nautilus:command", json.dumps(payload))
    return {"status": "sent", "cmd": request.cmd}

# --- WebSocket Telemetry ---

@APP.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    Forwards 'nautilus:stream' to the Frontend.
    """
    await websocket.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("nautilus:stream")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info("Telemetry Client Disconnected")
    except Exception as e:
        logger.error(f"Telemetry WS Error: {e}")
    finally:
        await pubsub.close()

# --- Static UI Serving ---
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse

candidate_paths = [
    "/app/frontend/dist",
    "frontend/dist",
    "/app/ops/static_ui",
    "static_ui",
    "/app/frontend/build"
]

static_dir = None
for path in candidate_paths:
    if os.path.exists(path) and os.path.isdir(path):
        static_dir = path
        break

if static_dir:
    logger.info(f"Serving static UI from {static_dir}")
    assets_path = os.path.join(static_dir, "assets")
    if os.path.exists(assets_path):
        APP.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    
    @APP.get("/{full_path:path}")
    async def serve_app(full_path: str):
        if full_path.startswith("api") or full_path.startswith("ws"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse({"detail": "Index not found"}, status_code=404)
else:
    logger.warning(f"Frontend build not found in {candidate_paths}")

