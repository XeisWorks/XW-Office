from __future__ import annotations

import importlib

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def test_customer_aftercare_migrations_are_idempotent_and_reversible() -> None:
    redelivery = importlib.import_module(
        "xw_office.migrations.versions.026_customer_aftercare_redelivery"
    )
    snooze = importlib.import_module(
        "xw_office.migrations.versions.027_customer_aftercare_snooze_context"
    )
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE customer_aftercare_case "
                "(id INTEGER PRIMARY KEY, status VARCHAR(20) NOT NULL)"
            )
        )
        connection.execute(
            text("CREATE TABLE customer_aftercare_item (id INTEGER PRIMARY KEY)")
        )
        operations = Operations(MigrationContext.configure(connection))
        redelivery.op = operations
        snooze.op = operations

        redelivery.upgrade()
        redelivery.upgrade()
        snooze.upgrade()
        snooze.upgrade()

        case_columns = {
            column["name"]
            for column in inspect(connection).get_columns("customer_aftercare_case")
        }
        item_columns = {
            column["name"]
            for column in inspect(connection).get_columns("customer_aftercare_item")
        }
        assert {"source_invoice_id", "dispatch_status", "snoozed_until"} <= case_columns
        assert {"source_kind", "origin_invoice_number"} <= item_columns
        assert "ix_customer_aftercare_case_snoozed_until" in {
            index["name"]
            for index in inspect(connection).get_indexes("customer_aftercare_case")
        }

        snooze.downgrade()
        redelivery.downgrade()

        assert {
            column["name"]
            for column in inspect(connection).get_columns("customer_aftercare_case")
        } == {"id", "status"}
        assert {
            column["name"]
            for column in inspect(connection).get_columns("customer_aftercare_item")
        } == {"id"}
