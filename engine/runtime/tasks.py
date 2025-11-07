from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Optional, Set

log = logging.getLogger(__name__)

_TASKS: Set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None) -> asyncio.Task[Any]:
    """Create and track an asyncio task, logging exceptions centrally."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:  # pragma: no cover - defensive
        raise RuntimeError("spawn() requires a running event loop") from exc

    task = loop.create_task(coro, name=name)
    _TASKS.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _TASKS.discard(t)
        try:
            exc = t.exception()
            if exc:
                log.exception("Background task %r crashed: %s", t.get_name(), exc)
        except asyncio.CancelledError:
            pass

    task.add_done_callback(_done)
    return task


async def shutdown(cancel_timeout: float = 5.0) -> None:
    """Cancel all tracked tasks and await their completion."""
    if not _TASKS:
        return

    tasks = list(_TASKS)
    for task in tasks:
        task.cancel()

    done, pending = await asyncio.wait(tasks, timeout=cancel_timeout)
    for task in pending:
        log.warning("Background task %r did not shut down in time", task.get_name())
    for task in done:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc:
            log.debug(
                "Background task %r finished with exception during shutdown: %s",
                task.get_name(),
                exc,
            )
