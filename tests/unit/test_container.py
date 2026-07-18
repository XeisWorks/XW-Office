"""Tests for DI container."""
import pytest

from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container


class _DummyService:
    def __init__(self, value: int) -> None:
        self.value = value


def test_register_and_resolve() -> None:
    container = Container(AppConfig())
    container.register(_DummyService, lambda c: _DummyService(42))
    svc = container.resolve(_DummyService)
    assert svc.value == 42


def test_singleton_behavior() -> None:
    container = Container(AppConfig())
    container.register(_DummyService, lambda c: _DummyService(1))
    a = container.resolve(_DummyService)
    b = container.resolve(_DummyService)
    assert a is b


def test_get_if_resolved_does_not_create_singleton() -> None:
    container = Container(AppConfig())
    container.register(_DummyService, lambda c: _DummyService(1))

    assert container.get_if_resolved(_DummyService) is None
    service = container.resolve(_DummyService)
    assert container.get_if_resolved(_DummyService) is service


def test_missing_factory_raises() -> None:
    container = Container(AppConfig())
    with pytest.raises(KeyError):
        container.resolve(_DummyService)
