"""Nautilus Ops package."""

# Ensure asyncio is available as a builtin for test modules that expect it.
import asyncio as _asyncio  # noqa: F401
import builtins as _builtins

if not hasattr(_builtins, "asyncio"):
    _builtins.asyncio = _asyncio

try:  # Compatibility shim for respx>=0.20
    import respx as _respx

    if not hasattr(_respx, "requests"):

        class _RequestsProxy:
            def __iter__(self):
                for call in _respx.calls:  # type: ignore[attr-defined]
                    yield call.request

            def __len__(self):
                return len(_respx.calls)  # type: ignore[attr-defined]

            def __getitem__(self, idx):
                return _respx.calls[idx].request  # type: ignore[attr-defined]

        _respx.requests = _RequestsProxy()  # type: ignore[attr-defined]
except ImportError:
    _respx = None  # type: ignore[assignment]

__all__ = []  # explicit namespace
