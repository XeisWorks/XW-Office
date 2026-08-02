"""Initial PostgreSQL core tables: pc_registry, setting_kv, api_secret.

Revision ID: 001_initial
Revises:
Create Date: 2026-02-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pc_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("machine_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column(
            "is_print_station",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_pc_registry_unique_machine", "pc_registry", ["machine_id"], unique=True)

    op.create_table(
        "setting_kv",
        sa.Column("key", sa.String(length=256), primary_key=True, nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "api_secret",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_api_secret_unique_name", "api_secret", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_secret_unique_name", table_name="api_secret")
    op.drop_table("api_secret")
    op.drop_table("setting_kv")
    op.drop_index("ix_pc_registry_unique_machine", table_name="pc_registry")
    op.drop_table("pc_registry")
