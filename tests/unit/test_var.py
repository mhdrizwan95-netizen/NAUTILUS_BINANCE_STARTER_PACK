from engine.risk_var import estimate_var_usd, sort_positions_by_var_desc


class P:
    def __init__(self, sym, entry, stop, qty, last=None):
        self.symbol = sym
        self.entry = entry
        self.stop = stop
        self.quantity = qty
        self.avg_price = entry
        self.last_price = last if last is not None else entry


def test_var_stop_first():
    p1 = P("AAAUSDT", 100, 95, 10)
    p2 = P("BBBUSDT", 10, 9, 20)
    ranked = sort_positions_by_var_desc([p1, p2], md=None)
    assert ranked[0].symbol == "AAAUSDT"


def test_var_atr_fallback():
    class MD:
        def atr(self, sym, tf, n):
            return 2.0 if sym == "CCCUSDT" else 1.0

    p3 = P("CCCUSDT", 50, None, 5)
    p4 = P("DDUSDT", 50, None, 10)
    ranked = sort_positions_by_var_desc([p3, p4], MD())
    # Both compute to 10; order can be either but both should be top two
    assert {ranked[0].symbol, ranked[1].symbol} == {"CCCUSDT", "DDUSDT"}

