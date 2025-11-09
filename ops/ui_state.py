"""State container for Command Center UI services."""

from __future__ import annotations

from typing import Any


class ServicesNotConfiguredError(RuntimeError):
    """Raised when UI services have not been registered."""


class UnknownServiceError(KeyError):
    """Raised when a requested service name is not configured."""


class _UiServiceRegistry:
    """Simple registry used to share service instances."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def configure(self, **services: Any) -> None:
        self._services.update(services)

    def get(self) -> dict[str, Any]:
        if not self._services:
            raise ServicesNotConfiguredError()
        return self._services

    def service(self, name: str) -> Any:
        services = self.get()
        if name not in services:
            raise UnknownServiceError(name)
        return services[name]


_REGISTRY = _UiServiceRegistry()


def configure(**services: Any) -> None:
    """Register service instances available to the UI API."""

    _REGISTRY.configure(**services)


def get_services() -> dict[str, Any]:
    """Return the full service mapping."""

    return _REGISTRY.get()


def get_service(name: str) -> Any:
    """Return a single named service."""

    return _REGISTRY.service(name)
