from __future__ import annotations


class Matcher:
    def __init__(self, store):
        self.store = store
        self.cool = {}

    def _ok(self, p, f):
        v = f.get(p.feat)
        if v is None:
            return False
        if p.op == ">":
            return v > p.value
        if p.op == "<":
            return v < p.value
        if p.op == "between":
            return p.low <= v <= p.high
        if p.op == "crosses_up":
            return f.get(p.feat + "_prev", -1e9) <= p.value < v
        if p.op == "crosses_down":
            return f.get(p.feat + "_prev", 1e9) >= p.value > v
        return False

    def evaluate(self, symbol, feats, ts):
        hits = []
        for s in self.store.active():
            key = (symbol, s.name)
            if ts < self.cool.get(key, 0):
                continue
            if feats.get("depth_usd", 0.0) < s.min_depth_usdt:
                continue
            if all(self._ok(p, feats) for p in s.predicates):
                hits.append(
                    {
                        "event_id": f"{symbol}:{s.name}:{ts}",
                        "ts": ts,
                        "symbol": symbol,
                        "situation": s.name,
                        "features": feats,
                        "priority": s.priority,
                    }
                )
                self.cool[key] = ts + s.cooldown_sec
        return hits
