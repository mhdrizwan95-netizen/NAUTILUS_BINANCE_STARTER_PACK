import types
import pytest

from engine.ops.stop_validator import StopValidator


class _Metrics:
    class _C:
        def labels(self, *a):
            return self

        def inc(self):
            return None

    stop_validator_missing_total = _C()
    stop_validator_repaired_total = _C()


class _MD:
    def atr(self, s, tf="1m", n=14):
        return 0.2

    def last(self, s):
        return 10.0


class _Router:
    def __init__(self):
        class _Pos:
            def __init__(self):
                from engine.core.portfolio import Position

                self.positions = {
                    "ABCUSDT": Position(
                        symbol="ABCUSDT", quantity=100.0, avg_price=10.0
                    )
                }

        self._state = _Pos()
        self._repaired = False

    def portfolio_service(self):
        return types.SimpleNamespace(state=self._state)

    async def list_open_protection(self, symbol):
        return []  # no protection

    async def amend_stop_reduce_only(self, symbol, side, stop_price, qty):
        self._repaired = True


@pytest.mark.asyncio
async def test_stop_validator_repairs_missing_sl():
    sv = StopValidator(
        {"STOP_VALIDATOR_ENABLED": True, "STOP_VALIDATOR_REPAIR": True},
        _Router(),
        _MD(),
        log=types.SimpleNamespace(warning=lambda *a, **k: None),
        metrics=_Metrics(),
    )
    await sv._validate_symbol("ABCUSDT")
    assert sv.router._repaired is True
