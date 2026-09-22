"""Parent-oriented product list read model ("Product List V2: expandable variants").

Curated grouping (``grouping.py``) already consolidates format/ensemble/scoring
variants of one fachliches product into a single ``Product`` with several
``ProductVariant`` rows — the "duplicate physical/digital rows" problem this module
was commissioned to fix is really "the list endpoint was still showing archived
(grouped-away) child products and had no per-variant aggregation", not a missing
grouping model. This module never re-groups anything (no fuzzy matching, no new
parent/child decisions) — it only *reads* the existing curated structure and shapes it
for the list UI.

Per-row metadata (format/ensemble/scoring/title_short/...) that a *grouped-away*
variant's original row carried lived in that row's own ``product.attributes`` before
grouping archived it — ``attributes`` is never touched by grouping. Grouping preserves
``Product.sku`` on the archived row and never touches ``ProductVariant.sku`` when moving
a variant — the two always still match — so this module recovers that metadata with a
single batched SKU lookup (``list_products_by_skus``) instead of a migration/backfill
step. See ``repositories/product_hub.py``'s own docstring on that method for the full
reasoning.

``product_identifier`` (ISBN/ASIN/...) is different: unlike ``attributes``, grouping
*does* reparent product-scoped identifiers onto the parent (see
``grouping.py``'s own ``reparent_identifier`` call) — so after a group has been
applied, every identifier for the whole group already lives under the parent's own
``product_id``. ISBN/ASIN are therefore aggregated per *parent* only
(``list_identifiers_for_products(product_ids)``, batched by the listed parents
directly), never attributed to one specific variant — the DB no longer records which
original row an already-reparented identifier came from.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from xw_office.models.product_hub import ChannelMapping, Product, ProductIdentifier, ProductPrice, ProductVariant
from xw_office.repositories.product_hub import ProductHubRepository

_NATURAL_SORT_SEGMENT = re.compile(r"(\d+)")

#: Rollup priority when combining several variants' channel state into one parent-row
#: state — a single failing/pending variant should never be masked by a synced one.
_STATE_PRIORITY = {"error": 0, "pending": 1, "synced": 2, "not_applicable": 3}


def natural_sku_key(sku: str) -> tuple[object, ...]:
    """Sort key for natural SKU ordering: numeric segments compare numerically, not
    lexicographically — ``XW-102`` before ``XW-1010``, ``XW-101.1`` before
    ``XW-101.10``. Splitting on digit runs and comparing digit segments as ``int``
    (others as lowercased ``str``) gives exactly that without a special case for the
    ``XW-`` prefix or ``.``/``-`` separators."""
    parts = _NATURAL_SORT_SEGMENT.split(sku or "")
    return tuple(int(part) if part.isdigit() else part.lower() for part in parts if part != "")


def _channel_state(*, sync_flag: bool | None, mapping: ChannelMapping | None) -> str:
    """One of "synced"/"error"/"pending"/"not_applicable" — see the build request's
    §12 symbol legend (✓/!/○/—). ``sync_flag`` is the seed's own explicit
    ``sync_wix``/``sync_sevdesk``/``sync_amazon`` hint; ``False`` means "deliberately
    not a channel product" (e.g. a sevdesk-only shipping line item), never a defect."""
    if mapping is not None:
        return "error" if mapping.sync_status in ("error", "conflict") else "synced"
    if sync_flag is False:
        return "not_applicable"
    return "pending"


def _rollup_state(states: list[str]) -> str:
    if not states:
        return "not_applicable"
    return min(states, key=lambda s: _STATE_PRIORITY.get(s, 99))


def _str_attr(attributes: dict[str, object], key: str) -> str | None:
    value = attributes.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bool_attr(attributes: dict[str, object], key: str) -> bool | None:
    value = attributes.get(key)
    return value if isinstance(value, bool) else None


def _music_attribute(attributes: dict[str, object], key: str) -> str | None:
    music = attributes.get("music_attributes")
    if isinstance(music, dict):
        value = music.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _current_price(prices: list[ProductPrice]) -> ProductPrice | None:
    current = [p for p in prices if p.valid_until is None]
    return current[0] if current else (prices[0] if prices else None)


@dataclass(frozen=True)
class VariantSummary:
    id: uuid.UUID
    sku: str
    name: str | None
    format: str | None
    ensemble: str | None
    scoring: str | None
    instrument: str | None
    is_default: bool
    active: bool
    price_net: Decimal | None
    price_gross: Decimal | None
    vat_percent: Decimal | None
    currency: str | None
    stock: int | None
    wix_state: str
    sevdesk_state: str
    amazon_state: str


@dataclass(frozen=True)
class ParentProductSummary:
    id: uuid.UUID
    display_sku: str
    name: str
    title_short: str | None
    category: str | None
    brand_name: str | None
    product_type: str
    status: str
    active: bool
    variant_count: int
    formats: list[str]
    ensembles: list[str]
    scorings: list[str]
    instruments: list[str]
    isbns: list[str]
    asins: list[str]
    price_net_min: Decimal | None
    price_net_max: Decimal | None
    price_gross_min: Decimal | None
    price_gross_max: Decimal | None
    currency: str | None
    stock_total: int | None
    tags: list[str]
    wix_state: str
    sevdesk_state: str
    amazon_state: str
    content_status: str | None
    review_required: bool
    row_version: int
    updated_at: datetime
    variants: list[VariantSummary] = field(default_factory=list)


def build_parent_product_summaries(
    repo: ProductHubRepository, products: list[Product]
) -> list[ParentProductSummary]:
    """Batched — a handful of queries for the whole page, never one per product."""
    if not products:
        return []

    product_ids = [p.id for p in products]
    variants = repo.list_variants_for_products(product_ids)
    variant_ids = [v.id for v in variants]

    source_skus = {p.sku for p in products} | {v.sku for v in variants}
    source_rows = repo.list_products_by_skus(list(source_skus))
    source_rows_by_sku = {p.sku: p for p in source_rows}

    # Unlike product.attributes (never touched by grouping), product_identifier rows
    # attached via product_id *are* reparented onto the parent when a child is grouped
    # in (see grouping.py's own reparent_identifier call) - so by the time a group has
    # been applied, every identifier for the whole group already lives on the parent's
    # own product_id. Batched by the listed parent ids directly, not by source SKU.
    identifiers_by_product: dict[uuid.UUID, list[ProductIdentifier]] = {}
    for identifier in repo.list_identifiers_for_products(product_ids):
        if identifier.product_id is not None:
            identifiers_by_product.setdefault(identifier.product_id, []).append(identifier)

    prices_by_variant: dict[uuid.UUID, list[ProductPrice]] = {}
    for price in repo.list_prices_for_variants(variant_ids):
        prices_by_variant.setdefault(price.variant_id, []).append(price)

    stock_by_variant = repo.sum_stock_on_hand_for_variants(variant_ids)

    product_mappings = repo.list_channel_mappings_for_entities(product_ids, entity_type="product")
    wix_by_product: dict[uuid.UUID, ChannelMapping] = {
        m.internal_entity_id: m for m in product_mappings if m.channel == "wix"
    }
    sevdesk_by_product: dict[uuid.UUID, ChannelMapping] = {
        m.internal_entity_id: m for m in product_mappings if m.channel == "sevdesk"
    }
    variant_mappings = repo.list_channel_mappings_for_entities(variant_ids, entity_type="variant")
    wix_by_variant: dict[uuid.UUID, ChannelMapping] = {
        m.internal_entity_id: m for m in variant_mappings if m.channel == "wix"
    }
    sevdesk_by_variant: dict[uuid.UUID, ChannelMapping] = {
        m.internal_entity_id: m for m in variant_mappings if m.channel == "sevdesk"
    }

    tags_by_product: dict[uuid.UUID, list[str]] = {}
    for product_id, label in repo.list_tag_labels_for_products(product_ids):
        tags_by_product.setdefault(product_id, []).append(label)

    variants_by_product: dict[uuid.UUID, list[ProductVariant]] = {}
    for variant in variants:
        variants_by_product.setdefault(variant.product_id, []).append(variant)

    summaries: list[ParentProductSummary] = []
    for product in products:
        product_variants = sorted(
            variants_by_product.get(product.id, []), key=lambda v: natural_sku_key(v.sku)
        )
        variant_summaries: list[VariantSummary] = []
        formats: list[str] = []
        ensembles: list[str] = []
        scorings: list[str] = []
        instruments: list[str] = []
        net_values: list[Decimal] = []
        gross_values: list[Decimal] = []
        currency: str | None = None
        variant_wix_states: list[str] = []
        any_review_required = bool(product.attributes.get("review_required"))

        for variant in product_variants:
            source = source_rows_by_sku.get(variant.sku, product)
            attrs = source.attributes or {}
            if attrs.get("review_required"):
                any_review_required = True
            fmt = _str_attr(attrs, "format")
            ensemble = _music_attribute(attrs, "ensemble")
            scoring = _music_attribute(attrs, "scoring")
            instrument = _music_attribute(attrs, "instrument")
            if fmt and fmt not in formats:
                formats.append(fmt)
            if ensemble and ensemble not in ensembles:
                ensembles.append(ensemble)
            if scoring and scoring not in scorings:
                scorings.append(scoring)
            if instrument and instrument not in instruments:
                instruments.append(instrument)

            current_price = _current_price(prices_by_variant.get(variant.id, []))
            if current_price is not None:
                if current_price.net_amount is not None:
                    net_values.append(current_price.net_amount)
                if current_price.gross_amount is not None:
                    gross_values.append(current_price.gross_amount)
                currency = currency or current_price.currency

            # Variant mappings are authoritative. A legacy product mapping may only
            # describe its default variant; applying it to every grouped sibling
            # would report false channel health.
            wix_state = _channel_state(
                sync_flag=_bool_attr(attrs, "sync_wix"),
                mapping=wix_by_variant.get(variant.id)
                or (wix_by_product.get(product.id) if variant.is_default else None),
            )
            variant_wix_states.append(wix_state)
            sevdesk_flag = _bool_attr(attrs, "sync_sevdesk")
            amazon_flag = _bool_attr(attrs, "sync_amazon")

            variant_summaries.append(
                VariantSummary(
                    id=variant.id,
                    sku=variant.sku,
                    name=variant.name,
                    format=fmt,
                    ensemble=ensemble,
                    scoring=scoring,
                    instrument=instrument,
                    is_default=variant.is_default,
                    active=variant.active,
                    price_net=current_price.net_amount if current_price else None,
                    price_gross=current_price.gross_amount if current_price else None,
                    vat_percent=(
                        current_price.tax_rate * 100
                        if current_price and current_price.tax_rate is not None
                        else None
                    ),
                    currency=current_price.currency if current_price else None,
                    stock=stock_by_variant.get(variant.id),
                    wix_state=wix_state,
                    sevdesk_state=_channel_state(
                        sync_flag=sevdesk_flag,
                        mapping=sevdesk_by_variant.get(variant.id)
                        or (sevdesk_by_product.get(product.id) if variant.is_default else None),
                    ),
                    amazon_state=_channel_state(sync_flag=amazon_flag, mapping=None),
                )
            )

        product_attrs = product.attributes or {}
        stock_values = [stock_by_variant[v.id] for v in product_variants if v.id in stock_by_variant]
        product_identifiers = identifiers_by_product.get(product.id, [])
        isbn13s = sorted({i.value for i in product_identifiers if i.scheme == "ISBN13"})
        isbn10s = sorted({i.value for i in product_identifiers if i.scheme == "ISBN10"})
        asins = sorted({i.value for i in product_identifiers if i.scheme == "ASIN"})

        summaries.append(
            ParentProductSummary(
                id=product.id,
                display_sku=_display_sku(product, product_variants),
                name=product.name,
                title_short=_str_attr(product_attrs, "title_short"),
                category=product.category,
                brand_name=product.brand_name,
                product_type=product.product_type,
                status=product.status,
                active=product.active,
                variant_count=len(product_variants),
                formats=formats,
                ensembles=ensembles,
                scorings=scorings,
                instruments=instruments,
                isbns=isbn13s or isbn10s,
                asins=asins,
                price_net_min=min(net_values) if net_values else None,
                price_net_max=max(net_values) if net_values else None,
                price_gross_min=min(gross_values) if gross_values else None,
                price_gross_max=max(gross_values) if gross_values else None,
                currency=currency,
                stock_total=sum(stock_values) if stock_values else None,
                tags=sorted(tags_by_product.get(product.id, [])),
                wix_state=_rollup_state(variant_wix_states),
                sevdesk_state=_rollup_state([v.sevdesk_state for v in variant_summaries]),
                amazon_state=_rollup_state([v.amazon_state for v in variant_summaries]),
                content_status=_str_attr(product_attrs, "content_status"),
                review_required=any_review_required,
                row_version=product.row_version,
                updated_at=product.updated_at,
                variants=variant_summaries,
            )
        )

    return summaries


def _display_sku(product: Product, variants: list[ProductVariant]) -> str:
    """1. the product's own SKU (== the canonical_variant's SKU by construction —
    every product is created with a variant sharing its own SKU, and grouping never
    changes either); 2. else the is_default variant's SKU; 3. else the
    naturally-smallest active variant SKU. Falls back through the chain only when the
    product's own SKU doesn't match any of its *current* variants (an inconsistency
    that shouldn't normally occur, but must never crash the list)."""
    variant_skus = {v.sku for v in variants}
    if product.sku in variant_skus:
        return product.sku
    default_variant = next((v for v in variants if v.is_default), None)
    if default_variant is not None:
        return default_variant.sku
    active_variants = sorted((v for v in variants if v.active), key=lambda v: natural_sku_key(v.sku))
    if active_variants:
        return active_variants[0].sku
    return product.sku
