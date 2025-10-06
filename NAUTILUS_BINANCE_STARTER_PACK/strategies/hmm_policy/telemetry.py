# M2: telemetry.py
class Telemetry:
    def __init__(self):
        self.counters = {}
    def count(self, key, labels=None):
        labels = labels or {}
        tup = (key, tuple(sorted(labels.items())))
        self.counters[tup] = self.counters.get(tup, 0) + 1
