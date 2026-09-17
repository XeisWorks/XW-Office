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
from decimal import Decimal
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
    #: Free-form bag (bullet_points, music_attributes, content_status, title_short,
    #: code_short, grouping hints, conflict_flags — see master_seed_import.py) — these
    #: aren't first-class columns yet, exposed as-is rather than one bespoke field each.
    attributes: dict[str, object] = {}


class ProductVariantSummaryOut(BaseModel):
    """One variant row within a :class:`ParentProductListItem`'s expandable section —
    mirrors ``catalog_list.VariantSummary``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str | None = None
    format: str | None = None
    ensemble: str | None = None
    scoring: str | None = None
    instrument: str | None = None
    is_default: bool
    active: bool
    price_net: Decimal | None = None
    price_gross: Decimal | None = None
    vat_percent: Decimal | None = None
    currency: str | None = None
    stock: int | None = None
    wix_state: str
    sevdesk_state: str
    amazon_state: str


class ParentProductListItem(BaseModel):
    """The product list's main row shape ("Product List V2: expandable variants") —
    one row per fachliches Product (curated grouping already consolidates format/
    ensemble/scoring variants into a single Product with several ProductVariant rows;
    this is the read model for that, not a second grouping step). Mirrors
    ``catalog_list.ParentProductSummary``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_sku: str
    name: str
    title_short: str | None = None
    category: str | None = None
    brand_name: str | None = None
    product_type: str
    status: str
    active: bool
    variant_count: int
    formats: list[str] = []
    ensembles: list[str] = []
    scorings: list[str] = []
    instruments: list[str] = []
    isbns: list[str] = []
    asins: list[str] = []
    price_net_min: Decimal | None = None
    price_net_max: Decimal | None = None
    price_gross_min: Decimal | None = None
    price_gross_max: Decimal | None = None
    currency: str | None = None
    stock_total: int | None = None
    tags: list[str] = []
    wix_state: str
    sevdesk_state: str
    amazon_state: str
    content_status: str | None = None
    review_required: bool
    row_version: int
    updated_at: datetime.datetime
    variants: list[ProductVariantSummaryOut] = []


class ProductVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str | None = None
    is_default: bool
    active: bool
    stock_enabled: bool
    row_version: int
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
    row_version: int


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
    row_version: int
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


# -- PR09: edit API -----------------------------------------------------------------
#
# Response schemas below add ``row_version`` (required by every PATCH's If-Match-style
# body) and expose entities PR07 never surfaced (tags, identifiers, prices, print
# rules, editions). Request bodies are intentionally separate models, not
# ``ProductDetail.model_copy(update=...)`` — every field is optional so a PATCH only
# sends what changed, and ``expected_row_version`` is required so the client can never
# forget it.


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    label: str


class TagAddRequest(BaseModel):
    tag_code: str


class IdentifierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scheme: str
    value: str
    variant_id: uuid.UUID | None = None
    market: str | None = None
    is_primary: bool


class IdentifierAddRequest(BaseModel):
    scheme: str
    value: str
    variant_id: uuid.UUID | None = None
    market: str = ""
    is_primary: bool = False


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    price_list_id: uuid.UUID
    currency: str
    net_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    tax_rate: Decimal | None = None
    valid_from: datetime.datetime
    valid_until: datetime.datetime | None = None


class PriceSetRequest(BaseModel):
    price_list_code: str
    currency: str = "EUR"
    net_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    tax_rate: Decimal | None = None


class PrintRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID
    min_stock_target: int
    reprint_batch_qty: int
    print_profile_id: str | None = None
    primary_print_asset_id: uuid.UUID | None = None
    row_version: int


class PrintRuleUpsertRequest(BaseModel):
    expected_row_version: int | None = None
    min_stock_target: int | None = None
    reprint_batch_qty: int | None = None
    print_profile_id: str | None = None
    primary_print_asset_id: uuid.UUID | None = None


class EditionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    label: str
    edition_number: int | None = None
    status: str
    published_at: datetime.date | None = None
    notes: str | None = None
    created_at: datetime.datetime


class EditionCreateRequest(BaseModel):
    label: str
    edition_number: int | None = None
    notes: str = ""
    resolve_improvement_ids: list[uuid.UUID] = []


class ProductUpdateRequest(BaseModel):
    expected_row_version: int
    name: str | None = None
    short_description: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    active: bool | None = None
    product_type: str | None = None
    brand_name: str | None = None
    release_date: datetime.date | None = None


class VariantUpdateRequest(BaseModel):
    expected_row_version: int
    name: str | None = None
    active: bool | None = None
    stock_enabled: bool | None = None
    weight_grams: Decimal | None = None


class AssetUpdateRequest(BaseModel):
    expected_row_version: int
    role: str | None = None
    sort_order: int | None = None


class ImprovementCreateRequest(BaseModel):
    description: str
    variant_id: uuid.UUID | None = None
    title: str = ""
    severity: str = "minor"


class ImprovementUpdateRequest(BaseModel):
    expected_row_version: int
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    status: str | None = None


class ContentGenerateResponse(BaseModel):
    """A draft — never auto-saved. Apply the description via the normal product
    PATCH; apply bullet points via ``PUT .../bullet-points``."""

    description: str
    bullet_points: list[str]


class BulletPointsUpdateRequest(BaseModel):
    expected_row_version: int
    bullet_points: list[str]
