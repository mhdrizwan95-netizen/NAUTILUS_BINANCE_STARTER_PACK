"""State container for Command Center UI services."""

from __future__ import annotations

from typing import Any, Dict


class _UiServiceRegistry:
    """Simple registry used to share service instances."""

    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def configure(self, **services: Any) -> None:
        self._services.update(services)

    def get(self) -> Dict[str, Any]:
        if not self._services:
            raise RuntimeError("UI services have not been configured")
        return self._services

    def service(self, name: str) -> Any:
        services = self.get()
        if name not in services:
            raise KeyError(f"Service '{name}' has not been configured")
        return services[name]


_REGISTRY = _UiServiceRegistry()


def configure(**services: Any) -> None:
    """Register service instances available to the UI API."""

    _REGISTRY.configure(**services)


def get_services() -> Dict[str, Any]:
    """Return the full service mapping."""

    return _REGISTRY.get()


def get_service(name: str) -> Any:
    """Return a single named service."""

    return _REGISTRY.service(name)
