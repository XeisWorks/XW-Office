"""Lightweight dependency injection container with lazy initialization."""
from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Callable, TypeVar

from xw_studio.core.config import AppConfig

logger = logging.getLogger(__name__)
T = TypeVar("T")


class Container:
    """Simple DI container: register factories, resolve singletons lazily."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._singletons: dict[type, object] = {}
        self._factories: dict[type, Callable[..., Any]] = {}
        self._lock = RLock()

    @property
    def config(self) -> AppConfig:
        return self._config

    def register(self, service_type: type[T], factory: Callable[[Container], T]) -> None:
        """Register a factory for a service type."""
        with self._lock:
            self._factories[service_type] = factory

    def resolve(self, service_type: type[T]) -> T:
        """Resolve a service instance (created once, then cached)."""
        with self._lock:
            if service_type not in self._singletons:
                if service_type not in self._factories:
                    raise KeyError(f"No factory registered for {service_type.__name__}")
                logger.debug("Creating singleton for %s", service_type.__name__)
                self._singletons[service_type] = self._factories[service_type](self)
            return self._singletons[service_type]  # type: ignore[return-value]

    def reset(self) -> None:
        """Clear all cached singletons (for testing)."""
        with self._lock:
            self._singletons.clear()
