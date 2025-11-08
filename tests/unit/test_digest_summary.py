import types

from engine.ops.digest import DigestJob


class FakeClock:
    def time(self):
        return 1_700_000_000


class FakeRollups:
    def __init__(self):
        self.cnt = {
            "trades": 7,
            "plans_live": 10,
            "plans_dry": 15,
            "half_applied": 4,
            "skip_late_chase": 3,
            "skip_spread": 2,
        }
        self.by_symbol = {
            ("trades", "ABCUSDT"): 3,
            ("trades", "XYZUSDT"): 2,
            ("trades", "DEFUSDT"): 2,
        }

    def top_symbols(self, key, k=5):
        xs = [(sym, n) for (kk, sym), n in self.by_symbol.items() if kk == key]
        return sorted(xs, key=lambda x: x[1], reverse=True)[:k]

    def maybe_reset(self):
        pass


class FakeTelegram:
    async def send(self, text, parse_mode="Markdown"):
        self.last = text


def test_digest_summary_basic(monkeypatch):
    # Ensure symbols included
    monkeypatch.setenv("DIGEST_INCLUDE_SYMBOLS", "true")
    rollups = FakeRollups()
    tg = FakeTelegram()
    job = DigestJob(
        rollups,
        tg,
        log=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
        clock=FakeClock(),
    )
    summary = job._summary()

    assert "*Event Breakout – Daily Digest*" in summary
    assert "Plans LIVE: *10*" in summary
    assert "Plans DRY: *15*" in summary
    assert "Trades: *7*" in summary
    assert "Efficiency (trades/live): *0.70*" in summary
    assert "Half-size applied: *4*" in summary
    assert "late_chase: *3*" in summary and "spread: *2*" in summary
    assert "Top traded:" in summary and "ABCUSDT *3*" in summary
