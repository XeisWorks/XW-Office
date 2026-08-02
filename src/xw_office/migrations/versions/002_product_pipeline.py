"""Product pipeline tables: product, sku_alias, print_rule, print_plan, inventory_movement.

Revision ID: 002_product_pipeline
Revises: 001_initial
Create Date: 2026-04-03

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_product_pipeline"
down_revision: Union[str, Sequence[str], None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # product — canonical product entity                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "product",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        # True => stockEnabled:false in sevDesk, show ∞, skip all print logic
        sa.Column(
            "is_digital", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("sevdesk_part_id", sa.String(length=32), nullable=True),
        sa.Column("wix_product_id", sa.String(length=64), nullable=True),
        # Local Windows path to the print-ready PDF
        sa.Column("print_file_path", sa.Text(), nullable=True),
        # Target on-hand stock for POD products (default 5)
        sa.Column("min_stock_target", sa.Integer(), nullable=False, server_default="5"),
        # How many to print per reprint run (default 3)
        sa.Column("reprint_batch_qty", sa.Integer(), nullable=False, server_default="3"),
        # Draft → review → live
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_product_sku", "product", ["sku"], unique=True)
    op.create_index("ix_product_sevdesk_part_id", "product", ["sevdesk_part_id"])
    op.create_index("ix_product_wix_product_id", "product", ["wix_product_id"])

    # ------------------------------------------------------------------ #
    # product_sku_alias — alternate SKUs resolving to the same product     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "product_sku_alias",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias_sku", sa.String(length=64), nullable=False),
        # Source tag: 'wix', 'sevdesk', 'legacy', 'manual'
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'manual'")),
    )
    op.create_index("ix_product_sku_alias_unique", "product_sku_alias", ["alias_sku"], unique=True)
    op.create_index("ix_product_sku_alias_product_id", "product_sku_alias", ["product_id"])

    # ------------------------------------------------------------------ #
    # inventory_movement — immutable audit log of every stock change       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "inventory_movement",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Positive = stock added (e.g. print run), negative = consumed (e.g. sale)
        sa.Column("delta", sa.Integer(), nullable=False),
        # Reason: 'print_run', 'sale', 'correction', 'recount'
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("invoice_ref", sa.String(length=128), nullable=True),
        sa.Column("sevdesk_part_id", sa.String(length=32), nullable=True),
        sa.Column("new_stock_after", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_inventory_movement_product_id", "inventory_movement", ["product_id"]
    )
    op.create_index(
        "ix_inventory_movement_occurred_at", "inventory_movement", ["occurred_at"]
    )

    # ------------------------------------------------------------------ #
    # print_plan — a batch print plan (one per START execution)            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "print_plan",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # pending / printing / done / cancelled
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("triggered_by_invoice", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------ #
    # print_plan_item — line items within a print plan                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "print_plan_item",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, nullable=False),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("print_plan.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("print_file_path", sa.Text(), nullable=True),
        # pending / printing / done / error
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_print_plan_item_plan_id", "print_plan_item", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_print_plan_item_plan_id", table_name="print_plan_item")
    op.drop_table("print_plan_item")
    op.drop_table("print_plan")
    op.drop_index("ix_inventory_movement_occurred_at", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_product_id", table_name="inventory_movement")
    op.drop_table("inventory_movement")
    op.drop_index("ix_product_sku_alias_product_id", table_name="product_sku_alias")
    op.drop_index("ix_product_sku_alias_unique", table_name="product_sku_alias")
    op.drop_table("product_sku_alias")
    op.drop_index("ix_product_wix_product_id", table_name="product")
    op.drop_index("ix_product_sevdesk_part_id", table_name="product")
    op.drop_index("ix_product_sku", table_name="product")
    op.drop_table("product")
