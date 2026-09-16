"""XW Product Hub — dealer sharing ORM models (PR12).

Schema per docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml. Only ``token_hash`` is
ever persisted (SHA-256 hex) — the plaintext share token is generated and returned
once at creation (see ``services/product_hub/sharing.py``) and never stored anywhere,
including here.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from xw_office.models.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

SHARE_STATUSES = ("active", "revoked", "expired")

#: The only fields a shared catalog view may ever expose — server-side allowlist per
#: the build plan's "field_whitelist" + "interne Felder koennen nicht von normaler
#: Editor-Rolle freigegeben werden" rule. Nothing outside this set can ever appear in
#: a share's ``field_whitelist``, checked at creation time
#: (``services/product_hub/sharing.py``), independent of what a caller requests.
ALLOWED_SHARE_FIELDS = (
    "cover_url",
    "sku",
    "isbn",
    "name",
    "description",
    "price_uvp",
    "price_b2b",
    "available",
)


class SharedCatalogView(Base):
    """Revocable, filtered, field-whitelisted dealer/public catalog view."""

    __tablename__ = "shared_catalog_view"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    filter_definition: Mapped[dict[str, object]] = mapped_column(
        JSONVariant, default=dict, nullable=False
    )
    field_whitelist: Mapped[list[object]] = mapped_column(JSONVariant, default=list, nullable=False)
    sort_definition: Mapped[list[object]] = mapped_column(JSONVariant, default=list, nullable=False)
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("price_list.id", ondelete="SET NULL"), nullable=True
    )
    allow_csv: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_xlsx: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_images: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_access_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ExportLog(Base):
    """One row per CSV/XLSX export served through a share."""

    __tablename__ = "export_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    shared_view_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shared_catalog_view.id", ondelete="SET NULL"), nullable=True, index=True
    )
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    requested_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


__all__ = [
    "JSONVariant",
    "SHARE_STATUSES",
    "ALLOWED_SHARE_FIELDS",
    "SharedCatalogView",
    "ExportLog",
]
