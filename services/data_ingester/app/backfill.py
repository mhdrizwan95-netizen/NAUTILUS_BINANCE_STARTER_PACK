import os
import time
from pathlib import Path
from typing import Optional

import ccxt  # type: ignore
import pandas as pd
from loguru import logger

from .config import settings
from common import manifest

EARLIEST_BINANCE_TS = 1502942400000  # 2017-08-17 00:00:00 UTC


def _exchange():
    exchange_cls = getattr(ccxt, settings.EXCHANGE)
    exchange = exchange_cls({"enableRateLimit": True})
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    if api_key and api_secret:
        exchange.apiKey = api_key
        exchange.secret = api_secret
    return exchange


def _landing_dir(symbol: str) -> Path:
    path = Path(settings.DATA_LANDING) / symbol.replace("/", "_") / settings.TIMEFRAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _initial_since(symbol: str) -> int:
    watermark_name = f"ingest:{settings.EXCHANGE}:{symbol}:{settings.TIMEFRAME}"
    watermark = manifest.get_watermark(
        watermark_name,
        default=None,
        db_path=settings.LEDGER_DB,
    )
    if watermark is not None:
        return watermark
    if settings.START_TS > 0:
        return settings.START_TS
    return EARLIEST_BINANCE_TS


def _target_end_ts() -> int:
    if settings.END_TS > 0:
        return settings.END_TS
    return int(time.time() * 1000)


def _write_chunk(symbol: str, frame: pd.DataFrame) -> Optional[str]:
    t_start = int(frame["timestamp"].min())
    t_end = int(frame["timestamp"].max())
    dest_dir = _landing_dir(symbol)
    dest = dest_dir / f"{symbol.replace('/', '_')}__{settings.TIMEFRAME}__{t_start}_{t_end}.csv"
    frame.to_csv(dest, index=False)
    file_id, inserted = manifest.register_file(
        str(dest),
        symbol=symbol,
        timeframe=settings.TIMEFRAME,
        t_start=t_start,
        t_end=t_end,
        db_path=settings.LEDGER_DB,
    )
    if not inserted:
        dest.unlink(missing_ok=True)
        return None
    return file_id


def _sleep():
    if settings.SLEEP_MS > 0:
        time.sleep(settings.SLEEP_MS / 1000.0)


def run_backfill() -> None:
    logger.info(
        "Starting Binance backfill job for symbols={} timeframe={}",
        settings.SYMBOLS,
        settings.TIMEFRAME,
    )
    manifest.init(settings.LEDGER_DB)
    exchange = _exchange()
    target_end = _target_end_ts()

    for symbol in settings.symbol_list:
        since = _initial_since(symbol)
        logger.info("Backfilling %s from %s up to %s", symbol, since, target_end)
        downloaded = 0

        while since < target_end:
            try:
                candles = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=settings.TIMEFRAME,
                    since=since,
                    limit=settings.BATCH_LIMIT,
                )
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Fetch error for %s at %s: %s", symbol, since, exc)
                _sleep()
                continue

            if not candles:
                logger.info("No more candles for %s; stopping.", symbol)
                break

            frame = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            frame = frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            frame = frame[frame["timestamp"] < target_end]

            if frame.empty:
                logger.info("Fetched candles exceed target end for %s; stopping.", symbol)
                break

            written = _write_chunk(symbol, frame)
            next_since = int(frame["timestamp"].max()) + 1
            manifest.set_watermark(
                f"ingest:{settings.EXCHANGE}:{symbol}:{settings.TIMEFRAME}",
                next_since,
                db_path=settings.LEDGER_DB,
            )
            since = next_since

            if written:
                downloaded += len(frame)
                logger.info(
                    "Saved %s rows for %s [%s -> %s] (total=%s)",
                    len(frame),
                    symbol,
                    int(frame["timestamp"].min()),
                    int(frame["timestamp"].max()),
                    downloaded,
                )
            else:
                logger.debug("Duplicate chunk ignored for %s at %s", symbol, next_since)

            _sleep()

        logger.info("Finished backfill for %s (downloaded %s rows)", symbol, downloaded)

    logger.info("Backfill job complete.")


def main() -> None:
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level=settings.LOG_LEVEL)
    run_backfill()


if __name__ == "__main__":
    main()
