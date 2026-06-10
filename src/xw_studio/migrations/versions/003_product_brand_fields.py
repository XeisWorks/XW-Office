"""Add brand fields to product pipeline.

Revision ID: 003_product_brand_fields
Revises: 002_product_pipeline
Create Date: 2026-06-10

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_product_brand_fields"
down_revision: Union[str, Sequence[str], None] = "002_product_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product", sa.Column("brand_name", sa.String(length=128), nullable=True))
    op.add_column("product", sa.Column("brand_id", sa.String(length=64), nullable=True))
    op.create_index("ix_product_brand_name", "product", ["brand_name"], unique=False)
    op.create_index("ix_product_brand_id", "product", ["brand_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_brand_id", table_name="product")
    op.drop_index("ix_product_brand_name", table_name="product")
    op.drop_column("product", "brand_id")
    op.drop_column("product", "brand_name")
