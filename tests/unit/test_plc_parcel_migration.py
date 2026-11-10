from __future__ import annotations

import importlib

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def test_plc_evidence_migration_upgrades_existing_shipment_table() -> None:
    migration = importlib.import_module("xw_office.migrations.versions.037_plc_parcel_evidence")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE plc_shipment (id CHAR(32) PRIMARY KEY)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        tables = set(inspect(connection).get_table_names())
        assert {"plc_parcel_manifest", "plc_tracking_event"} <= tables
        columns = {column["name"] for column in inspect(connection).get_columns("plc_shipment")}
        assert "response_collo_codes_json" in columns
        migration.downgrade()
        assert "plc_parcel_manifest" not in inspect(connection).get_table_names()
