"""Fix a name collision: migration 002 already created a legacy, product-keyed
``inventory_movement`` table (the desktop app's original stock ledger, columns
``id``/``product_id``/``delta``/``reason``/``invoice_ref``/``sevdesk_part_id``/
``new_stock_after``/``note``/``occurred_at``) years before migration 014's variant-keyed
Inventory V2 shadow-mode ledger of the same name was designed. 014's own
``if "inventory_movement" not in existing_tables`` guard then silently skipped
creating the *new* table in any environment where 002 had already run — which is
every real environment, including production. Confirmed empirically during the
Master Seed V2 replace (2026-09-17, see docs/product_hub/PROGRESS.md): production's
``inventory_movement`` has the *legacy* schema, no ``variant_id`` column at all, and
``InventoryRepository``/``InventoryV2Service`` would fail outright against it the
first time shadow mode actually recorded a real movement (it never has).

Fix: give PR13/14's ledger its own, collision-free name,
``product_hub_inventory_movement``, and create it here (``inventory_movement`` itself
is untouched — it stays exactly as migration 002 left it, still owned by the legacy
desktop inventory path). No production data migration needed: the old table has 0
rows tied to this shadow-mode feature (it was never successfully written to), and the
new table starts empty either way.

Revision ID: 015_inventory_movement_rename
Revises: 014_product_hub_inventory
Create Date: 2026-09-17

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015_inventory_movement_rename"
down_revision: Union[str, Sequence[str], None] = "014_product_hub_inventory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLE = "product_hub_inventory_movement"


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

    if _NEW_TABLE in existing_tables:
        return

    op.create_table(
        _NEW_TABLE,
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
        f"ix_{_NEW_TABLE}_idempotency_key",
        _NEW_TABLE,
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        f"ix_{_NEW_TABLE}_variant_location",
        _NEW_TABLE,
        ["variant_id", "location_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(f"ix_{_NEW_TABLE}_variant_location", table_name=_NEW_TABLE)
    op.drop_index(f"ix_{_NEW_TABLE}_idempotency_key", table_name=_NEW_TABLE)
    op.drop_table(_NEW_TABLE)
