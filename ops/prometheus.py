"""
Shared Prometheus registry setup with multiprocess support for the ops service.

Each uvicorn worker owns its own in-memory registry but metrics are aggregated
through `prometheus_client.multiprocess` using the configured data directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
    multiprocess,
)

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
    except OSError:
        # Best-effort cleanup; failures should not block service startup.
        return


REGISTRY = CollectorRegistry()

if _MULTIPROC_DIR:
    _cleanup_multiproc_dir(_MULTIPROC_DIR)
    multiprocess.MultiProcessCollector(REGISTRY)


def _get_existing_metric(name: str):
    """Return an already-registered metric if it exists in the shared registry."""
    collectors = getattr(REGISTRY, "_names_to_collectors", {})  # type: ignore[attr-defined]
    return collectors.get(name)


def get_or_create_counter(name: str, documentation: str, **kwargs) -> Counter:
    """Create a Counter unless it already exists (useful across reloads/tests)."""
    existing = _get_existing_metric(name)
    if existing:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, registry=REGISTRY, **kwargs)


def get_or_create_gauge(name: str, documentation: str, **kwargs) -> Gauge:
    """Create a Gauge unless it already exists (useful across reloads/tests)."""
    existing = _get_existing_metric(name)
    if existing:
        return existing  # type: ignore[return-value]
    return Gauge(name, documentation, registry=REGISTRY, **kwargs)


def render_latest() -> tuple[bytes, str]:
    """Return the latest metrics exposition payload and content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = ["REGISTRY", "render_latest"]
