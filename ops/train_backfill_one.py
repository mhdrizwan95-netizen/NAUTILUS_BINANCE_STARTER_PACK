#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess as sp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURSOR = ROOT / "ops" / "training_cursor.json"


class CommandFailed(SystemExit):
    """Raised when a shell command exits non-zero."""

    def __init__(self, cmd: str) -> None:
        super().__init__(f"Command failed: {cmd}")


class TrainingCursorMissing(SystemExit):
    """Raised when the training cursor file is missing."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Missing training cursor file: {path}")


def run(cmd: str) -> None:
    print(">>", cmd, flush=True)
    rc = sp.call(cmd, shell=True)
    if rc != 0:
        raise CommandFailed(cmd)


def load_cursor() -> dict:
    if not CURSOR.exists():
        raise TrainingCursorMissing(CURSOR)
    c = json.loads(CURSOR.read_text())
    c["next_date"] = dt.date.fromisoformat(c["next_date"])  # type: ignore[assignment]
    c["lower_bound"] = dt.date.fromisoformat(c["lower_bound"])  # type: ignore[assignment]
    return c


def save_cursor(c: dict, next_date: dt.date) -> None:
    c2 = dict(c)
    c2["next_date"] = next_date.isoformat()
    CURSOR.write_text(json.dumps(c2, indent=2))


def day_paths(symbol: str, day: dt.date) -> dict[str, Path]:
    dstr = day.isoformat()
    return dict(
        raw=ROOT / f"data/raw/binance/spot/1m/{symbol}/{day.year}/{dstr}.parquet",
        feat=ROOT / f"data/features/1m/{symbol}/{dstr}.parquet",
        hits=ROOT / f"data/hits/{symbol}_{dstr}.parquet",
        out=ROOT / f"data/outcomes/{symbol}_{dstr}.parquet",
    )


def cleanup_day(day: dt.date, symbols: list[str]) -> None:
    for s in symbols:
        for p in day_paths(s, day).values():
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass


def main() -> None:
    os.chdir(ROOT)
    cur = load_cursor()
    day: dt.date = cur["next_date"]
    lb: dt.date = cur["lower_bound"]
    symbols: list[str] = list(cur.get("symbols", []))
    wrap: bool = bool(cur.get("wrap_mode", False))

    if day < lb:
        if wrap:
            day = dt.date.today() - dt.timedelta(days=1)
        else:
            print(f"[trainer] reached lower_bound {lb}; nothing to do.")
            return

    day_str = day.isoformat()

    # Step 1: Download Binance day for all symbols
    syms_arg = ",".join(symbols)
    run(f'python adapters/binance_hist.py --symbols "{syms_arg}" --day "{day_str}"')

    # Step 2: Build features (uses --range day..day)
    run(f'python pipeline/build_features.py --symbols "{syms_arg}" --range "{day_str}..{day_str}"')

    # Step 3: Replay situations
    run(
        f'python pipeline/replay_situations.py --symbols "{syms_arg}" --range "{day_str}..{day_str}"'
    )

    # Step 4: Simulate
    run(
        f'python pipeline/sim_exec.py --symbols "{syms_arg}" --range "{day_str}..{day_str}" --model quarantine'
    )

    # Step 5: Seed live learner: post each outcome row to situations /feedback/outcome
    endpoint = os.getenv("SITU_ENDPOINT", "http://situations:8011/feedback/outcome")
    for s in symbols:
        out_file = ROOT / f"data/outcomes/{s}_{day_str}.parquet"
        if out_file.exists():
            run(
                f'python pipeline/seed_feedback_api.py --hits "{out_file}" --endpoint "{endpoint}" || true'
            )

    # Step 6: Cleanup the day to save disk
    cleanup_day(day, symbols)

    # Step 7: Move cursor backwards
    prev_day = day - dt.timedelta(days=1)
    save_cursor(cur, prev_day)
    print(f"[trainer] completed {day_str}, next_date set to {prev_day}")


if __name__ == "__main__":
    main()
