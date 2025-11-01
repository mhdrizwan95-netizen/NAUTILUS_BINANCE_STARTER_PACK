import os
import time
from pathlib import Path
from fastapi import FastAPI
from loguru import logger
import ccxt
import pandas as pd

from .config import settings
from common import manifest

app = FastAPI(title="data-ingester", version="0.1.0")


def _client():
    ex = getattr(ccxt, settings.EXCHANGE)()
    # Optionally configure apiKey/secret via env for private endpoints if needed
    if os.getenv("API_KEY"):
        ex.apiKey = os.getenv("API_KEY")
    if os.getenv("API_SECRET"):
        ex.secret = os.getenv("API_SECRET")
    return ex


def _landing_dir(sym: str, tf: str) -> Path:
    p = Path(settings.DATA_LANDING) / sym.replace("/", "_") / tf
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.on_event("startup")
def on_start():
    Path(settings.DATA_LANDING).mkdir(parents=True, exist_ok=True)
    Path(settings.LEDGER_DB).parent.mkdir(parents=True, exist_ok=True)
    manifest.init(settings.LEDGER_DB)
    logger.info("data-ingester up")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest_once")
def ingest_once():
    ex = _client()
    tf = settings.TIMEFRAME
    out = {"downloaded": 0}
    for sym in [s.strip() for s in settings.SYMBOLS.split(",") if s.strip()]:
        wm_name = f"ingest:{settings.EXCHANGE}:{sym}:{tf}"
        since = manifest.get_watermark(
            wm_name, default=settings.START_TS, db_path=settings.LEDGER_DB
        )
        if since is None:
            since = 0
        # ccxt expects ms
        dl_dir = _landing_dir(sym, tf)
        try:
            # fetch in chunks
            int(time.time() * 1000)
            batch = ex.fetch_ohlcv(
                sym, timeframe=tf, since=since, limit=settings.BATCH_LIMIT
            )
            if not batch:
                continue
            df = pd.DataFrame(
                batch, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            t_start = int(df["timestamp"].min())
            t_end = int(df["timestamp"].max())
            # Write CSV with deterministic name
            name = f"{sym.replace('/','_')}__{tf}__{t_start}_{t_end}.csv"
            path = str((dl_dir / name).resolve())
            df.to_csv(path, index=False)
            # Register in ledger (dedup by sha256)
            file_id, inserted = manifest.register_file(
                path=path,
                symbol=sym,
                timeframe=tf,
                t_start=t_start,
                t_end=t_end,
                db_path=settings.LEDGER_DB,
            )
            if inserted:
                out["downloaded"] += len(df)
                # Advance watermark conservatively to t_end + 1ms to avoid overlap
                manifest.set_watermark(wm_name, t_end + 1, db_path=settings.LEDGER_DB)
            else:
                # Duplicate content; delete the file immediately
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        except Exception as e:
            logger.exception(f"ingest error for {sym}: {e}")
        # Respect extra delay to avoid rate limits
        try:
            delay = max(int(settings.SLEEP_MS), 0) / 1000.0
            if delay > 0:
                time.sleep(delay)
        except Exception:
            pass
    return out
