"""Pydantic response models for the Product Hub Read API (PR07).

These are the **internal** API's schemas — protected by the same bearer-token
dependency as the rest of this service, meant for XW-Office Desktop and a future
authenticated WebUI. They deliberately still only expose *metadata* for
``PRINT_PDF`` assets (path string, health status — never a download/stream), per the
confirmed architecture decision; a future public/dealer-share schema (PR12) must
define its own, separately field-whitelisted models rather than reusing these.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Generic limit/offset pagination envelope."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ProductListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    slug: str
    status: str
    active: bool
    product_type: str
    brand_name: str | None = None
    category: str | None = None
    row_version: int
    updated_at: datetime.datetime


class ProductDetail(ProductListItem):
    short_description: str | None = None
    description: str | None = None
    family_id: uuid.UUID | None = None
    release_date: datetime.date | None = None
    created_at: datetime.datetime
    archived_at: datetime.datetime | None = None


class ProductVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str | None = None
    is_default: bool
    active: bool
    stock_enabled: bool
    updated_at: datetime.datetime


class ProductAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    role: str
    sort_order: int
    storage_kind: str
    uri: str
    mime_type: str | None = None
    size_bytes: int | None = None
    source_channel: str | None = None
    source_external_id: str | None = None
    public_share_allowed: bool
    health_status: str
    last_checked_at: datetime.datetime | None = None


class ProductImprovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    title: str | None = None
    description: str
    source: str
    severity: str
    status: str
    created_at: datetime.datetime
    resolved_at: datetime.datetime | None = None


class ChannelMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    entity_type: str
    external_id: str
    sync_status: str
    last_pulled_at: datetime.datetime | None = None
    last_pushed_at: datetime.datetime | None = None
    last_success_at: datetime.datetime | None = None
    last_error: str | None = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_type: str
    actor_id: str | None = None
    source: str
    action: str
    changed_fields: list[str]
    created_at: datetime.datetime


class ProductReadinessOut(BaseModel):
    """Mirrors :class:`xw_office.services.product_hub.readiness.ProductReadiness`."""

    model_config = ConfigDict(from_attributes=True)

    wix_ready: bool
    wix_missing: list[str]
    b2b_ready: bool
    b2b_missing: list[str]
    print_ready: bool
    print_missing: list[str]
    sevdesk_ready: bool
    sevdesk_missing: list[str]


class ReadinessSummaryOut(BaseModel):
    """Mirrors :class:`xw_office.services.product_hub.readiness.ReadinessSummary`."""

    model_config = ConfigDict(from_attributes=True)

    total_products: int
    wix_ready: int
    b2b_ready: int
    print_ready: int
    sevdesk_ready: int
    missing_cover: int
    open_improvements: int
