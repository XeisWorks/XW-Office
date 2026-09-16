"""XW Product Hub PR09: row_version columns for optimistic-locked editing.

Additive from head 010_product_hub_import_staging. ``product.row_version`` already
exists (migration 009); this adds the same optimistic-locking column to the other
entity types PR09's edit API covers directly (``product_variant``, ``product_asset``,
``print_rule``, ``product_improvement``). Existing rows backfill to 1 via
``server_default``, matching the pattern used for ``product.row_version``.

Prices (``product_price``) are deliberately excluded: PR09 "edits" a price by writing
a new effective-dated row and closing the previous one, never by mutating a row in
place, so no optimistic lock is needed there. Categories/tags are join tables
(``product_category``/``product_tag``) edited via idempotent add/remove, not PATCH.

This migration does not write to Wix or sevdesk and does not touch
``SettingKV["inventory.products"]`` / ``inventory.stock_levels``.

Revision ID: 011_product_hub_row_versions
Revises: 010_product_hub_import_staging
Create Date: 2026-09-16

Note: kept to 28 characters — ``alembic_version.version_num`` is ``VARCHAR(32)``
(set by alembic's own bootstrap migration, not something this project's migrations
control), so anything longer fails the final version-stamp UPDATE after the DDL has
already run. A first attempt named ``011_product_hub_editable_row_versions`` (38
chars) hit exactly this and rolled back cleanly (Postgres DDL is transactional) —
recorded here so the next migration doesn't repeat it.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_product_hub_row_versions"
down_revision: Union[str, Sequence[str], None] = "010_product_hub_import_staging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("product_variant", "product_asset", "print_rule", "product_improvement")


def upgrade() -> None:
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.drop_column(table_name, "row_version")
