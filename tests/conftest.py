"""Shared test fixtures for XeisWorks Office."""
from __future__ import annotations

import pytest

from xw_office.core.config import AppConfig
from xw_office.core.container import Container


@pytest.fixture
def app_config() -> AppConfig:
    """Minimal test configuration."""
    return AppConfig()


@pytest.fixture
def container(app_config: AppConfig) -> Container:
    """DI container with test config."""
    return Container(app_config)
