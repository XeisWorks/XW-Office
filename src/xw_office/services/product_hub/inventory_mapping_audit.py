"""Safe exact-SKU candidates for the Product-Hub inventory source contract.

The inventory cutover must never guess a sevDesk Part for a grouped product.
This helper therefore emits candidates only when both sides have a unique,
non-empty SKU and the Hub variant is an active physical stock item.  It is
deliberately read-only; applying a candidate remains a separate, audited
mapping action.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from xw_office.models.product_hub import ChannelMapping, Product, ProductVariant
from xw_office.services.sevdesk.part_client import SevdeskPart


@dataclass(frozen=True)
class ExactSevdeskMappingCandidate:
    variant_id: str
    product_id: str
    sku: str
    title: str
    sevdesk_part_id: str
    sevdesk_sku: str

    def as_dict(self) -> dict[str, str]:
        return {
            "variant_id": self.variant_id,
            "product_id": self.product_id,
            "sku": self.sku,
            "title": self.title,
            "sevdesk_part_id": self.sevdesk_part_id,
            "sevdesk_sku": self.sevdesk_sku,
        }


def exact_sevdesk_mapping_candidates(
    products: Iterable[Product],
    variants: Iterable[ProductVariant],
    parts: Iterable[SevdeskPart],
    mappings: Iterable[ChannelMapping] = (),
) -> list[ExactSevdeskMappingCandidate]:
    """Return only unambiguous exact SKU candidates.

    Product-level mappings are intentionally not inferred here.  A product with
    more than one active stock-enabled variant must be resolved at variant level,
    even if a legacy parent Part-ID exists.
    """
    product_by_id = {product.id: product for product in products}
    active_variants = [
        variant
        for variant in variants
        if variant.active and variant.stock_enabled and variant.product_id in product_by_id
    ]
    variant_count_by_product: dict[object, int] = {}
    for variant in active_variants:
        variant_count_by_product[variant.product_id] = variant_count_by_product.get(variant.product_id, 0) + 1

    existing_variant_ids = {
        mapping.internal_entity_id
        for mapping in mappings
        if mapping.channel == "sevdesk" and mapping.entity_type == "variant"
    }
    parts_by_sku: dict[str, list[SevdeskPart]] = {}
    for part in parts:
        sku = str(part.sku or "").strip().upper()
        part_id = str(part.id or "").strip()
        if sku and part_id:
            parts_by_sku.setdefault(sku, []).append(part)

    variant_by_sku: dict[str, list[ProductVariant]] = {}
    for variant in active_variants:
        sku = str(variant.sku or "").strip().upper()
        if sku:
            variant_by_sku.setdefault(sku, []).append(variant)

    candidates: list[ExactSevdeskMappingCandidate] = []
    for sku, matching_variants in variant_by_sku.items():
        matching_parts = parts_by_sku.get(sku, [])
        if len(matching_variants) != 1 or len(matching_parts) != 1:
            continue
        variant = matching_variants[0]
        if variant.id in existing_variant_ids:
            continue
        product = product_by_id[variant.product_id]
        # Parent-level compatibility is safe only for a single active variant;
        # do not suggest a duplicate child mapping for an already mapped parent.
        if variant_count_by_product.get(product.id, 0) == 1:
            parent_mapped = any(
                mapping.channel == "sevdesk"
                and mapping.entity_type == "product"
                and mapping.internal_entity_id == product.id
                for mapping in mappings
            )
            if parent_mapped or str(product.sevdesk_part_id or "").strip():
                continue
        part = matching_parts[0]
        candidates.append(
            ExactSevdeskMappingCandidate(
                variant_id=str(variant.id),
                product_id=str(product.id),
                sku=str(variant.sku).strip(),
                title=str(variant.name or product.name or "").strip(),
                sevdesk_part_id=str(part.id).strip(),
                sevdesk_sku=str(part.sku).strip(),
            )
        )
    return sorted(candidates, key=lambda item: (item.sku.upper(), item.variant_id))


__all__ = ["ExactSevdeskMappingCandidate", "exact_sevdesk_mapping_candidates"]
