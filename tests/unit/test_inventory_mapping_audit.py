from __future__ import annotations

import uuid
from types import SimpleNamespace

from xw_office.services.product_hub.inventory_mapping_audit import exact_sevdesk_mapping_candidates
from xw_office.services.sevdesk.part_client import SevdeskPart


def _product(*, product_id: uuid.UUID, part_id: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=product_id, name="Title", sevdesk_part_id=part_id)


def _variant(*, product_id: uuid.UUID, sku: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), product_id=product_id, sku=sku, name="Variant",
        active=True, stock_enabled=True,
    )


def test_exact_mapping_preview_only_returns_unique_unmapped_pairs() -> None:
    product_id = uuid.uuid4()
    product = _product(product_id=product_id)
    variant = _variant(product_id=product_id, sku="XW-001")
    candidates = exact_sevdesk_mapping_candidates(
        [product], [variant], [SevdeskPart(id="part-1", sku="xw-001", name="Part")]
    )

    assert [candidate.as_dict() for candidate in candidates] == [{
        "variant_id": str(variant.id),
        "product_id": str(product_id),
        "sku": "XW-001",
        "title": "Variant",
        "sevdesk_part_id": "part-1",
        "sevdesk_sku": "xw-001",
    }]


def test_exact_mapping_preview_skips_duplicate_part_and_parent_fallback() -> None:
    product_id = uuid.uuid4()
    product = _product(product_id=product_id, part_id="legacy-part")
    variant_a = _variant(product_id=product_id, sku="XW-001")
    variant_b = _variant(product_id=product_id, sku="XW-002")
    parts = [
        SevdeskPart(id="part-a", sku="XW-001", name="A"),
        SevdeskPart(id="part-b", sku="XW-001", name="Duplicate"),
        SevdeskPart(id="part-c", sku="XW-002", name="B"),
    ]

    candidates = exact_sevdesk_mapping_candidates([product], [variant_a, variant_b], parts)

    assert [candidate.sku for candidate in candidates] == ["XW-002"]
