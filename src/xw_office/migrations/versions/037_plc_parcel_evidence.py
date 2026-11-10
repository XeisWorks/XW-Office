"""Persist parcel contents, code assignment and Post tracking events.

Revision ID: 037_plc_parcel_evidence
Revises: 036_inventory_external_mirror
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "037_plc_parcel_evidence"
down_revision = "036_inventory_external_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {str(column["name"]) for column in inspector.get_columns("plc_shipment")}
    if "response_collo_codes_json" not in columns:
        op.add_column(
            "plc_shipment",
            sa.Column("response_collo_codes_json", sa.Text(), nullable=False, server_default="[]"),
        )
    tables = set(inspector.get_table_names())
    if "plc_parcel_manifest" not in tables:
        op.create_table(
            "plc_parcel_manifest",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("shipment_id", sa.Uuid(), sa.ForeignKey("plc_shipment.id"), nullable=False),
            sa.Column("package_number", sa.Integer(), nullable=False),
            sa.Column("parcel_reference", sa.String(100), nullable=False, server_default=""),
            sa.Column("weight_kg", sa.Numeric(8, 3), nullable=True),
            sa.Column("contents_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("tracking_code", sa.String(100), nullable=False, server_default=""),
            sa.Column("code_assignment", sa.String(24), nullable=False, server_default=""),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("packing_pdf_sha256", sa.String(64), nullable=False, server_default=""),
            sa.UniqueConstraint("shipment_id", "package_number", name="uq_plc_parcel_shipment_number"),
        )
        op.create_index("ix_plc_parcel_manifest_shipment_id", "plc_parcel_manifest", ["shipment_id"])
        op.create_index("ix_plc_parcel_manifest_tracking_code", "plc_parcel_manifest", ["tracking_code"])
    if "plc_tracking_event" not in tables:
        op.create_table(
            "plc_tracking_event",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("tracking_code", sa.String(100), nullable=False),
            sa.Column("event_id", sa.String(100), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False),
            sa.Column("event_type", sa.String(16), nullable=False),
            sa.Column("event_reason", sa.String(16), nullable=False, server_default=""),
            sa.Column("event_postal_code", sa.String(16), nullable=False, server_default=""),
            sa.Column("event_city", sa.String(100), nullable=False, server_default=""),
            sa.Column("event_country", sa.String(2), nullable=False, server_default=""),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.UniqueConstraint("tracking_code", "event_id", name="uq_plc_tracking_code_event"),
        )
        op.create_index("ix_plc_tracking_event_tracking_code", "plc_tracking_event", ["tracking_code"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "plc_tracking_event" in tables:
        op.drop_index("ix_plc_tracking_event_tracking_code", table_name="plc_tracking_event")
        op.drop_table("plc_tracking_event")
    if "plc_parcel_manifest" in tables:
        op.drop_index("ix_plc_parcel_manifest_tracking_code", table_name="plc_parcel_manifest")
        op.drop_index("ix_plc_parcel_manifest_shipment_id", table_name="plc_parcel_manifest")
        op.drop_table("plc_parcel_manifest")
    columns = {str(column["name"]) for column in inspector.get_columns("plc_shipment")}
    if "response_collo_codes_json" in columns:
        op.drop_column("plc_shipment", "response_collo_codes_json")
