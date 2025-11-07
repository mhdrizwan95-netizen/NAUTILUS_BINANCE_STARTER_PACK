class SimClock:
    def __init__(self):
        self._t = 0
        self._step = 0

    def set(self, t_ms: int):
        self._t = int(t_ms)

    def now_ms(self) -> int:
        return self._t

    def tick(self, t_ms: int):
        self._t = int(t_ms)
        self._step += 1

    @property
    def step(self):
        return self._step
