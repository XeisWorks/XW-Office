"""Persistent Product Hub conflict wizard.

Revision ID: 016_conflict_wizard
Revises: 015_inventory_movement_rename
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "016_conflict_wizard"
down_revision = "015_inventory_movement_rename"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "conflict_scan" not in existing:
        op.create_table(
            "conflict_scan",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("scan_type", sa.String(40), nullable=False),
            sa.Column("source_scope", json_type, nullable=False),
            sa.Column("product_scope", json_type, nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.Column("products_scanned", sa.Integer(), nullable=False),
            sa.Column("differences_found", sa.Integer(), nullable=False),
            sa.Column("cases_created", sa.Integer(), nullable=False),
            sa.Column("cases_updated", sa.Integer(), nullable=False),
            sa.Column("auto_resolved", sa.Integer(), nullable=False),
            sa.Column("error_summary", sa.Text()),
        )
    if "conflict_case" not in existing:
        op.create_table(
            "conflict_case",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "product_id",
                sa.Uuid(),
                sa.ForeignKey("product.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "variant_id", sa.Uuid(), sa.ForeignKey("product_variant.id", ondelete="CASCADE")
            ),
            sa.Column(
                "origin_sync_conflict_id",
                sa.Uuid(),
                sa.ForeignKey("sync_conflict.id", ondelete="SET NULL"),
            ),
            sa.Column("conflict_type", sa.String(60), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("priority_score", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("summary", sa.Text()),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("snoozed_until", sa.DateTime(timezone=True)),
            sa.Column("assigned_to", sa.String(160)),
            sa.Column("resolution_type", sa.String(40)),
            sa.Column("resolution_note", sa.Text()),
            sa.Column(
                "source_scan_id", sa.Uuid(), sa.ForeignKey("conflict_scan.id", ondelete="SET NULL")
            ),
            sa.Column(
                "reopened_from_case_id",
                sa.Uuid(),
                sa.ForeignKey("conflict_case.id", ondelete="SET NULL"),
            ),
            sa.Column("dedupe_key", sa.String(500), nullable=False),
            sa.Column("occurrence", sa.Integer(), nullable=False),
            sa.Column("hub_row_version", sa.Integer(), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "dedupe_key", "occurrence", name="uq_conflict_case_dedupe_occurrence"
            ),
        )
        op.create_index(
            "ix_conflict_case_queue", "conflict_case", ["status", "severity", "priority_score"]
        )
        op.create_index("ix_conflict_case_product", "conflict_case", ["product_id", "status"])
        op.create_index(
            "ix_conflict_case_origin_sync_conflict_id", "conflict_case", ["origin_sync_conflict_id"]
        )
    if "conflict_field" not in existing:
        op.create_table(
            "conflict_field",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "conflict_case_id",
                sa.Uuid(),
                sa.ForeignKey("conflict_case.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("field_path", sa.String(240), nullable=False),
            sa.Column("selected_value", json_type),
            sa.Column("selected_source", sa.String(20)),
            sa.Column("resolution_type", sa.String(40)),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "conflict_case_id", "field_path", name="uq_conflict_field_case_path"
            ),
        )
        op.create_index(
            "ix_conflict_field_conflict_case_id", "conflict_field", ["conflict_case_id"]
        )
    if "conflict_observation" not in existing:
        op.create_table(
            "conflict_observation",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "conflict_field_id",
                sa.Uuid(),
                sa.ForeignKey("conflict_field.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("raw_value", json_type),
            sa.Column("normalized_value", json_type),
            sa.Column("source_external_id", sa.String(240)),
            sa.Column("source_revision", sa.String(240)),
            sa.Column("source_hash", sa.String(64), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "conflict_field_id",
                "source",
                "source_hash",
                name="uq_conflict_observation_snapshot",
            ),
        )
        op.create_index(
            "ix_conflict_observation_field_source",
            "conflict_observation",
            ["conflict_field_id", "source"],
        )
    if "conflict_action" not in existing:
        op.create_table(
            "conflict_action",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "conflict_case_id",
                sa.Uuid(),
                sa.ForeignKey("conflict_case.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("action_type", sa.String(80), nullable=False),
            sa.Column("field_path", sa.String(240)),
            sa.Column("before_value", json_type),
            sa.Column("after_value", json_type),
            sa.Column("selected", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column(
                "outbox_event_id", sa.Uuid(), sa.ForeignKey("outbox_event.id", ondelete="SET NULL")
            ),
            sa.Column("error", sa.Text()),
            sa.Column("attempted_at", sa.DateTime(timezone=True)),
            sa.Column("verified_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_conflict_action_case", "conflict_action", ["conflict_case_id", "created_at"]
        )
    if "resolution_rule" not in existing:
        op.create_table(
            "resolution_rule",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("code", sa.String(120), unique=True, nullable=False),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("scope", json_type, nullable=False),
            sa.Column("conditions", json_type, nullable=False),
            sa.Column("action", json_type, nullable=False),
            sa.Column("risk_level", sa.String(20), nullable=False),
            sa.Column("auto_apply", sa.Boolean(), nullable=False),
            sa.Column(
                "created_from_case_id",
                sa.Uuid(),
                sa.ForeignKey("conflict_case.id", ondelete="SET NULL"),
            ),
            sa.Column("created_by", sa.String(160)),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in (
        "resolution_rule",
        "conflict_action",
        "conflict_observation",
        "conflict_field",
        "conflict_case",
        "conflict_scan",
    ):
        op.drop_table(table)
