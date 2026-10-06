"""Isolated own print articles, without SKU or Office foreign keys.

Revision ID: 020_print_center
Revises: 019_product_asset_jobs
"""
from __future__ import annotations

from alembic import op
from sqlalchemy.schema import CreateSchema

from xw_office.print_center.models import PrintCenterBase

revision = "020_print_center"
down_revision = "019_product_asset_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(CreateSchema("print_center", if_not_exists=True))
    PrintCenterBase.metadata.create_all(bind)


def downgrade() -> None:
    PrintCenterBase.metadata.drop_all(op.get_bind())
