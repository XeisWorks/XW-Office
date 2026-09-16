"""XW Product Hub PR13/PR14: Inventory V2 ledger (shadow mode) + alerts.

Additive from head 013_product_hub_sharing. Schema per
docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml: ``inventory_location``,
``inventory_stock``, ``inventory_movement`` (append-only ledger), ``inventory_alert``.

This is explicitly **shadow mode** (build plan PR13: "Hub-Lagerledger aufbauen, noch
ohne finalen Master-Cutover"): nothing here is read by the legacy print/fulfillment
paths yet, and this migration does not touch ``SettingKV["inventory.products"]`` /
``inventory.stock_levels`` — those remain the operative inventory source until the
PR15 cutover (not attempted in this build round; see docs/product_hub/PROGRESS.md for
why).

Revision ID: 014_product_hub_inventory
Revises: 013_product_hub_sharing
Create Date: 2026-09-16

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_product_hub_inventory"
down_revision: Union[str, Sequence[str], None] = "013_product_hub_sharing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "inventory_location" not in existing_tables:
        op.create_table(
            "inventory_location",
            _uuid_pk(),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
        op.create_index(
            "ix_inventory_location_code", "inventory_location", ["code"], unique=True
        )

    if "inventory_stock" not in existing_tables:
        op.create_table(
            "inventory_stock",
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="RESTRICT"),
                primary_key=True,
            ),
            sa.Column(
                "location_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("inventory_location.id", ondelete="RESTRICT"),
                primary_key=True,
            ),
            sa.Column("on_hand", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reorder_point", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("target_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("default_reprint_qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint("on_hand >= 0", name="ck_inventory_stock_on_hand_non_negative"),
            sa.CheckConstraint("reserved >= 0", name="ck_inventory_stock_reserved_non_negative"),
        )

    if "inventory_movement" not in existing_tables:
        op.create_table(
            "inventory_movement",
            _uuid_pk(),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "location_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("inventory_location.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(40), nullable=False),
            sa.Column("source", sa.String(80), nullable=False),
            sa.Column("external_reference", sa.String(240), nullable=True),
            sa.Column("idempotency_key", sa.String(240), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("on_hand_after", sa.Integer(), nullable=False),
            sa.Column("actor", sa.String(160), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_inventory_movement_idempotency_key",
            "inventory_movement",
            ["idempotency_key"],
            unique=True,
        )
        op.create_index(
            "ix_inventory_movement_variant_location",
            "inventory_movement",
            ["variant_id", "location_id", "occurred_at"],
        )

    if "inventory_alert" not in existing_tables:
        op.create_table(
            "inventory_alert",
            _uuid_pk(),
            sa.Column(
                "variant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("product_variant.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "location_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("inventory_location.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("type", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
            sa.Column("threshold", sa.Integer(), nullable=True),
            sa.Column("observed_stock", sa.Integer(), nullable=True),
            sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("xw_flow_task_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("xw_flow_client_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        # Partial unique index: at most one OPEN alert per (variant, location, type).
        # Postgres-only (partial indexes aren't portable to SQLite, same reasoning as
        # the "one default variant" note in models/product_hub.py) - the repository
        # layer enforces this dialect-portably for the SQLite test suite.
        op.execute(
            "CREATE UNIQUE INDEX ix_inventory_alert_open_unique "
            "ON inventory_alert (variant_id, location_id, type) "
            "WHERE status = 'open'"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_inventory_alert_open_unique")
    op.drop_table("inventory_alert")
    op.drop_index("ix_inventory_movement_variant_location", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_idempotency_key", table_name="inventory_movement")
    op.drop_table("inventory_movement")
    op.drop_table("inventory_stock")
    op.drop_index("ix_inventory_location_code", table_name="inventory_location")
    op.drop_table("inventory_location")
