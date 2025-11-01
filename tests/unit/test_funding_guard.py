import types
import pytest

from engine.guards.funding_guard import FundingGuard


class _Client:
    async def bulk_premium_index(self):
        return {
            "BTCUSDT": {"lastFundingRate": "0.0020"},  # 0.2%
        }


class _Router:
    def __init__(self):
        class _S:
            def __init__(self):
                from engine.core.portfolio import Position

                self.positions = {
                    "BTCUSDT": Position(
                        symbol="BTCUSDT", quantity=0.1, avg_price=20000.0
                    )
                }

        self._state = _S()
        self.trimmed = False

    def exchange_client(self):
        return _Client()

    def portfolio_service(self):
        return types.SimpleNamespace(state=self._state)

    async def place_reduce_only_market(self, symbol, side, qty):
        self.trimmed = True


class _Bus:
    def fire(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_funding_guard_trims(monkeypatch):
    monkeypatch.setenv("FUNDING_GUARD_ENABLED", "true")
    monkeypatch.setenv("FUNDING_SPIKE_THRESHOLD", "0.15")
    monkeypatch.setenv("FUNDING_TRIM_PCT", "0.30")
    r = _Router()
    g = FundingGuard(r, bus=_Bus())
    await g.tick()
    assert r.trimmed is True
