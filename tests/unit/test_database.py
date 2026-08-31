"""Tests for database helpers."""
from sqlalchemy import create_engine, inspect

import pytest

from xw_office.core.config import AppConfig
from xw_office.core.database import create_engine_from_config, ensure_core_tables


def test_create_engine_requires_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_engine_from_config(AppConfig())


def test_create_engine_rejects_invalid_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL is invalid"):
        create_engine_from_config(AppConfig(database_url="postgresql://user:pw@host:port/db"))


def test_ensure_core_tables_creates_missing_tables() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)

    try:
        created_tables = ensure_core_tables(engine)
        expected = {
            "api_secret",
            "customer_aftercare_case",
            "customer_aftercare_item",
            "expense_ignore_rule",
            "expense_shift_entry",
            "pc_registry",
            "plc_shipment",
            "setting_kv",
        }
        assert set(created_tables) == expected
        assert expected.issubset(
            set(inspect(engine).get_table_names())
        )
        assert ensure_core_tables(engine) == ()
    finally:
        engine.dispose()
