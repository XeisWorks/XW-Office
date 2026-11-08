"""Add idempotent invoice-position inventory booking checkpoints."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "030_inventory_document_booking"
down_revision = "029_tax_followup_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_document_booking" in set(inspector.get_table_names()):
        return
    op.create_table(
        "inventory_document_booking",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(128), nullable=False),
        sa.Column("position_key", sa.String(160), nullable=False),
        sa.Column("movement_kind", sa.String(24), nullable=False),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variant.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_revision", sa.String(240), nullable=False, server_default=""),
        sa.Column("last_idempotency_key", sa.String(240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "document_id", "position_key", "movement_kind",
            name="uq_inventory_document_booking_position",
        ),
    )
    op.create_index(
        "ix_inventory_document_booking_document_id",
        "inventory_document_booking",
        ["document_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "inventory_document_booking" in set(inspector.get_table_names()):
        op.drop_table("inventory_document_booking")
