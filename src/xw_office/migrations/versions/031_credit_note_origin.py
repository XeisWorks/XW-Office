"""Track credit-note origin positions for bounded return quantities."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "031_credit_note_origin"
down_revision = "030_inventory_document_booking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inventory_document_booking")}
    if "original_document_id" not in columns:
        op.add_column(
            "inventory_document_booking",
            sa.Column("original_document_id", sa.String(128), nullable=False, server_default=""),
        )
    if "original_position_key" not in columns:
        op.add_column(
            "inventory_document_booking",
            sa.Column("original_position_key", sa.String(160), nullable=False, server_default=""),
        )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("inventory_document_booking")}
    if "ix_inventory_document_booking_credit_origin" not in indexes:
        op.create_index(
            "ix_inventory_document_booking_credit_origin",
            "inventory_document_booking",
            ["original_document_id", "original_position_key", "movement_kind"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_document_booking" not in set(inspector.get_table_names()):
        return
    indexes = {index["name"] for index in inspector.get_indexes("inventory_document_booking")}
    if "ix_inventory_document_booking_credit_origin" in indexes:
        op.drop_index("ix_inventory_document_booking_credit_origin", table_name="inventory_document_booking")
    columns = {column["name"] for column in inspector.get_columns("inventory_document_booking")}
    if "original_position_key" in columns:
        op.drop_column("inventory_document_booking", "original_position_key")
    if "original_document_id" in columns:
        op.drop_column("inventory_document_booking", "original_document_id")
