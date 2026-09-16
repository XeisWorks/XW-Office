"""Channel readiness calculation (PR07).

Read-only, pure calculation against the canonical schema — see
docs/product_hub/XW_PRODUCT_HUB_DEEP_RESEARCH.md §11 for the source criteria.

Two criteria are deliberately approximated rather than built out in full here, since
the tables/fields they would need are not populated by any PR up to and including
PR07 (pricing/print-rule/tax-rate/unity commit is out of PR06's scope; a dedicated
``channel_category_mapping`` curation flow does not exist yet):

- "Wix/sevdesk-Kategorie gemappt" is approximated as "has at least one internal
  category" / "has a channel_mapping for that channel" respectively. A precise check
  against ``channel_category_mapping`` is a natural refinement once that table has
  read/write support.
- "Retail/B2B-Preis vorhanden" and "Druckprofil vorhanden" check the real
  ``product_price``/``print_rule`` tables — they will correctly show as *missing* for
  nearly every product today, because PR06 deliberately does not auto-create prices
  (ambiguous Excel data) and no print rule has been curated yet. That is accurate,
  not a bug: readiness is supposed to show real gaps, not invented ones.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from xw_office.models.product_hub import Product, ProductVariant
from xw_office.repositories.product_hub import ProductHubRepository

_B2B_TAG_CODE = "b2b"


@dataclass(frozen=True)
class ProductReadiness:
    """Per-product readiness across the four channel-readiness dimensions."""

    product_id: uuid.UUID
    wix_ready: bool
    wix_missing: list[str]
    b2b_ready: bool
    b2b_missing: list[str]
    print_ready: bool
    print_missing: list[str]
    sevdesk_ready: bool
    sevdesk_missing: list[str]


@dataclass
class ReadinessSummary:
    """Catalog-wide readiness counts — the build plan's "Channel Readiness" dashboard."""

    total_products: int = 0
    wix_ready: int = 0
    b2b_ready: int = 0
    print_ready: int = 0
    sevdesk_ready: int = 0
    missing_cover: int = 0
    open_improvements: int = 0


def evaluate_product_readiness(product_repo: ProductHubRepository, product: Product) -> ProductReadiness:
    """Evaluate one product's readiness. Read-only — never writes anything."""
    default_variant = product_repo.get_default_variant(product.id)
    assets = product_repo.list_assets(product.id)
    tags = {link.tag_id for link in product_repo.list_product_tags(product.id)}
    categories = product_repo.list_product_categories(product.id)
    channels = {
        mapping.channel
        for mapping in product_repo.list_channel_mappings(
            entity_type="product", internal_entity_id=product.id
        )
    }

    has_cover = any(asset.role == "COVER" for asset in assets)
    has_description = bool((product.description or "").strip())
    has_name = bool((product.name or "").strip())
    has_sku = bool((product.sku or "").strip())
    has_category = bool(categories)
    has_b2b_tag = _has_tag_code(product_repo, tags, _B2B_TAG_CODE)

    retail_price = _has_active_price(product_repo, default_variant, "RETAIL_EUR")
    b2b_price = _has_active_price(product_repo, default_variant, "B2B_EUR")

    print_asset_ok = any(
        asset.role == "PRINT_PDF" and asset.storage_kind == "NETWORK_PATH" and asset.health_status == "ok"
        for asset in assets
    )
    print_rule = product_repo.get_print_rule(default_variant.id) if default_variant is not None else None
    has_print_profile = bool(print_rule and (print_rule.print_profile_id or print_rule.print_plan))

    wix_missing = _missing(
        [
            ("SKU", has_sku),
            ("Name", has_name),
            ("Retail-Preis", retail_price),
            ("Cover", has_cover),
            ("Beschreibung", has_description),
            ("Wix-Kategorie", has_category),
        ]
    )
    b2b_missing = _missing(
        [
            ("Tag B2B", has_b2b_tag),
            ("SKU", has_sku),
            ("Name", has_name),
            ("Händlerpreis", b2b_price),
            ("Cover", has_cover),
            ("Beschreibung", has_description),
        ]
    )
    print_missing = _missing(
        [
            ("Produktions-PDF (Health ok)", print_asset_ok),
            ("Druckprofil/-plan", has_print_profile),
        ]
    )
    sevdesk_missing = _missing(
        [
            ("SKU", has_sku),
            ("Name", has_name),
            ("sevdesk-Kategorie-Mapping", "sevdesk" in channels),
        ]
    )

    return ProductReadiness(
        product_id=product.id,
        wix_ready=not wix_missing,
        wix_missing=wix_missing,
        b2b_ready=not b2b_missing,
        b2b_missing=b2b_missing,
        print_ready=not print_missing,
        print_missing=print_missing,
        sevdesk_ready=not sevdesk_missing,
        sevdesk_missing=sevdesk_missing,
    )


def build_readiness_summary(product_repo: ProductHubRepository, products: list[Product]) -> ReadinessSummary:
    summary = ReadinessSummary(total_products=len(products))
    for product in products:
        readiness = evaluate_product_readiness(product_repo, product)
        if readiness.wix_ready:
            summary.wix_ready += 1
        if readiness.b2b_ready:
            summary.b2b_ready += 1
        if readiness.print_ready:
            summary.print_ready += 1
        if readiness.sevdesk_ready:
            summary.sevdesk_ready += 1
        if not any(asset.role == "COVER" for asset in product_repo.list_assets(product.id)):
            summary.missing_cover += 1
        summary.open_improvements += sum(
            1 for item in product_repo.list_improvements(product.id) if item.status == "open"
        )
    return summary


def _missing(checks: list[tuple[str, bool]]) -> list[str]:
    return [label for label, ok in checks if not ok]


def _has_tag_code(product_repo: ProductHubRepository, tag_ids: set[uuid.UUID], code: str) -> bool:
    """Read-only: never creates the tag — a readiness check must not have side effects."""
    if not tag_ids:
        return False
    tag = product_repo.find_tag_by_code(code)
    return tag is not None and tag.id in tag_ids


def _has_active_price(
    product_repo: ProductHubRepository, variant: ProductVariant | None, price_list_code: str
) -> bool:
    if variant is None:
        return False
    price_list = product_repo.get_price_list_by_code(price_list_code)
    if price_list is None:
        return False
    return any(price.price_list_id == price_list.id for price in product_repo.list_prices(variant.id))


__all__ = [
    "ProductReadiness",
    "ReadinessSummary",
    "evaluate_product_readiness",
    "build_readiness_summary",
]
