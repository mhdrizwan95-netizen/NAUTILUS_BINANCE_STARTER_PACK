import time
from contextlib import contextmanager
from typing import Any


class LoopGuardAbort(RuntimeError):
    def __init__(self, name: str, iteration: int, elapsed: float, state: dict[str, Any] | None):
        super().__init__(
            f"[LoopGuard] {name} abort at i={iteration}, t={elapsed:.3f}s, state={state}"
        )


class LoopGuard:
    def __init__(
        self,
        *,
        max_iter: int = 10_000_000,
        timeout_s: float = 10.0,
        sample_every: int = 10_000,
        name: str = "loop",
    ) -> None:
        self.max_iter = max_iter
        self.timeout_s = timeout_s
        self.sample_every = sample_every
        self.name = name
        self._i = 0
        self._start = time.perf_counter()

    def tick(self, state: dict[str, Any] | None = None) -> None:
        self._i += 1
        if self._i % self.sample_every != 0:
            return
        elapsed = time.perf_counter() - self._start
        if self._i >= self.max_iter or elapsed >= self.timeout_s:
            raise LoopGuardAbort(self.name, self._i, elapsed, state)


@contextmanager
def loop_guard_context(**kwargs):
    guard = LoopGuard(**kwargs)
    yield guard
