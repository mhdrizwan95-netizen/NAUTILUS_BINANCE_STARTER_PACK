from __future__ import annotations

import argparse
import glob
import json
import logging

import httpx
import pandas as pd

logger = logging.getLogger("pipeline.seed_feedback")
_LOAD_ERRORS = (OSError, ValueError, FileNotFoundError, pd.errors.EmptyDataError)
_REQUEST_ERRORS = (httpx.HTTPError, ConnectionError)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


def post_outcomes(pattern: str, endpoint: str, timeout: float = 2.0) -> int:
    paths = sorted(glob.glob(pattern))
    if not paths:
        return 0
    total = 0
    with httpx.Client(timeout=timeout) as client:
        for path in paths:
            try:
                df = pd.read_parquet(path)
            except _LOAD_ERRORS as exc:
                _log_suppressed(f"seed_feedback.load.{path}", exc)
                continue
            for row in df.itertuples(index=False):
                payload = {
                    "event_id": getattr(row, "event_id", None),
                    "situation": getattr(row, "situation", None),
                    "pnl_usd": float(getattr(row, "pnl_usd", 0.0)),
                    "hold_sec": int(getattr(row, "hold_sec", 0)),
                    "filled": bool(getattr(row, "filled", True)),
                }
                try:
                    r = client.post(endpoint, json=payload)
                    r.raise_for_status()
                    total += 1
                except _REQUEST_ERRORS as exc:
                    _log_suppressed("seed_feedback.post", exc)
                    continue
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed situation feedback API with offline outcomes")
    ap.add_argument(
        "--hits",
        required=True,
        help="File pattern for outcomes, e.g. data/outcomes/BTCUSDT_2025-10-05.parquet or data/outcomes/*.parquet",
    )
    ap.add_argument("--endpoint", default="http://localhost:8011/feedback/outcome")
    args = ap.parse_args()
    n = post_outcomes(args.hits, args.endpoint)
    print(json.dumps({"posted": n}))


if __name__ == "__main__":
    main()
