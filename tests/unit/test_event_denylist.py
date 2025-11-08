import logging

import pytest

from engine.strategies.event_breakout import BreakoutConfig, EventBreakout


@pytest.mark.asyncio
async def test_event_breakout_denylist_skips(caplog, tmp_path):
    caplog.set_level(logging.INFO)
    cfg = BreakoutConfig(
        enabled=True,
        dry_run=True,
        denylist_enabled=True,
        denylist_path=str(tmp_path / "denylist.txt"),
    )
    # Write denylist file
    (tmp_path / "denylist.txt").write_text("PEPEUSDT\n# comment\n")

    class _Router:
        async def get_last_price(self, s):
            return 10.0

    class _MD:
        def last(self, s):
            return 10.0

        def klines(self, s, interval, limit):
            return [[0, 10, 10.1, 9.9, 10, 1000, 0, 600000] for _ in range(limit)]

        def book_ticker(self, s):
            return {"bidPrice": 9.97, "askPrice": 10.03}

    bo = EventBreakout(_Router(), md=_MD(), cfg=cfg)
    await bo.on_event({"symbol": "PEPEUSDT", "time": int(__import__("time").time() * 1000)})
    # Denylist skip should be logged; no dry plan line
    messages = [r.message for r in caplog.records]
    assert any("denylist skip" in m for m in messages)
    assert not any("[EVENT-BO:DRY] PEPEUSDT" in m for m in messages)
