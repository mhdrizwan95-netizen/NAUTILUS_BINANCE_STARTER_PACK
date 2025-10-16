"""
Shared Prometheus registry setup with multiprocess support for the ops service.

Each uvicorn worker owns its own in-memory registry but metrics are aggregated
through `prometheus_client.multiprocess` using the configured data directory.
"""
from __future__ import annotations

import os
from pathlib import Path

from prometheus_client import CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest, multiprocess

_MULTIPROC_DIR = os.getenv("PROMETHEUS_MULTIPROC_DIR")


def _cleanup_multiproc_dir(path: str) -> None:
    """Remove stale metric shard files left from previous runs."""
    try:
        directory = Path(path)
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            return
        for child in directory.iterdir():
            if child.suffix == ".db":
                child.unlink(missing_ok=True)
    except Exception:
        # Best-effort cleanup; failures should not block service startup.
        pass


REGISTRY = CollectorRegistry()

if _MULTIPROC_DIR:
    _cleanup_multiproc_dir(_MULTIPROC_DIR)
    multiprocess.MultiProcessCollector(REGISTRY)


def render_latest() -> tuple[bytes, str]:
    """Return the latest metrics exposition payload and content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = ["REGISTRY", "render_latest"]
