"""Tests for the parent-oriented product list read model (Product List V2)."""
from __future__ import annotations

from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.services.product_hub.catalog_list import (
    build_parent_product_summaries,
    natural_sku_key,
)
from xw_office.services.product_hub.grouping import GroupingService


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


@pytest.fixture
def grouping(session_factory: sessionmaker[Session]) -> GroupingService:
    return GroupingService(session_factory)


# -- natural_sku_key -----------------------------------------------------------------


def test_natural_sku_key_orders_numeric_segments_numerically() -> None:
    skus = ["XW-101.10", "XW-101.2", "XW-101.1", "XW-1010", "XW-102", "XW-101"]
    assert sorted(skus, key=natural_sku_key) == [
        "XW-101",
        "XW-101.1",
        "XW-101.2",
        "XW-101.10",
        "XW-102",
        "XW-1010",
    ]


# -- build_parent_product_summaries ---------------------------------------------------


def test_empty_input_returns_empty_list(product_repo: ProductHubRepository) -> None:
    assert build_parent_product_summaries(product_repo, []) == []


def test_singleton_product_reads_format_from_its_own_attributes(
    product_repo: ProductHubRepository,
) -> None:
    product, variant = product_repo.create_product(sku="XW-1", name="Solo")
    product_repo.update_product(
        product.id, expected_row_version=product.row_version, attributes={"format": "PHYSICAL"}
    )
    product = product_repo.get_product(product.id)
    assert product is not None

    [summary] = build_parent_product_summaries(product_repo, [product])

    assert summary.display_sku == "XW-1"
    assert summary.variant_count == 1
    assert summary.formats == ["PHYSICAL"]
    assert summary.variants[0].sku == variant.sku


def test_grouped_parent_recovers_variant_metadata_from_archived_sibling_by_sku(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    """The core trick this module relies on: after grouping, the child's per-row
    format/ensemble data is recovered by matching Product.sku == variant.sku, not
    from the (now-reparented) variant's own product_id."""
    parent, _parent_variant = product_repo.create_product(sku="XW-102.5", name="Volksmusik #2 - Tuba in B")
    product_repo.update_product(
        parent.id, expected_row_version=parent.row_version, attributes={"format": "PHYSICAL"}
    )
    child, child_variant = product_repo.create_product(
        sku="XW-102.5-D", name="Volksmusik #2 - Tuba in B"
    )
    product_repo.update_product(
        child.id, expected_row_version=child.row_version, attributes={"format": "DIGITAL"}
    )

    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])
    refreshed_parent = product_repo.get_product(parent.id)
    assert refreshed_parent is not None

    [summary] = build_parent_product_summaries(product_repo, [refreshed_parent])

    assert summary.variant_count == 2
    assert set(summary.formats) == {"PHYSICAL", "DIGITAL"}
    by_sku = {v.sku: v for v in summary.variants}
    assert by_sku["XW-102.5"].format == "PHYSICAL"
    assert by_sku[child_variant.sku].format == "DIGITAL"


def test_price_min_max_aggregated_across_variants(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    with session_factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail"))
        session.commit()
    price_list = product_repo.get_price_list_by_code("RETAIL_EUR")
    assert price_list is not None

    parent, parent_variant = product_repo.create_product(sku="XW-1", name="Basis")
    product_repo.set_price(parent_variant.id, price_list_id=price_list.id, gross_amount=Decimal("9.90"), net_amount=Decimal("9.00"))
    child, child_variant = product_repo.create_product(sku="XW-1-D", name="Basis")
    product_repo.set_price(child_variant.id, price_list_id=price_list.id, gross_amount=Decimal("5.50"), net_amount=Decimal("5.00"))

    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])
    refreshed_parent = product_repo.get_product(parent.id)
    assert refreshed_parent is not None

    [summary] = build_parent_product_summaries(product_repo, [refreshed_parent])

    assert summary.price_gross_min == Decimal("5.50")
    assert summary.price_gross_max == Decimal("9.90")
    assert summary.price_net_min == Decimal("5.00")
    assert summary.price_net_max == Decimal("9.00")


def test_sevdesk_only_product_reports_not_applicable_wix_state(
    product_repo: ProductHubRepository,
) -> None:
    product, _variant = product_repo.create_product(sku="XW-900", name="Versand")
    product_repo.update_product(
        product.id, expected_row_version=product.row_version, attributes={"sync_wix": False}
    )
    product = product_repo.get_product(product.id)
    assert product is not None

    [summary] = build_parent_product_summaries(product_repo, [product])

    assert summary.wix_state == "not_applicable"


def test_wix_mapping_present_reports_synced_state(product_repo: ProductHubRepository) -> None:
    product, _variant = product_repo.create_product(sku="XW-1", name="A")
    product_repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="handle-1"
    )
    product = product_repo.get_product(product.id)
    assert product is not None

    [summary] = build_parent_product_summaries(product_repo, [product])

    assert summary.wix_state == "synced"


def test_variant_level_channel_mappings_drive_grouped_variant_states(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, parent_variant = product_repo.create_product(sku="XW-1", name="A")
    child, child_variant = product_repo.create_product(sku="XW-1-D", name="A")
    product_repo.create_channel_mapping(
        channel="sevdesk", entity_type="variant", internal_entity_id=child_variant.id, external_id="part-2"
    )
    product_repo.create_channel_mapping(
        channel="wix", entity_type="variant", internal_entity_id=child_variant.id, external_id="wix-2"
    )
    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])
    refreshed_parent = product_repo.get_product(parent.id)
    assert refreshed_parent is not None

    [summary] = build_parent_product_summaries(product_repo, [refreshed_parent])
    by_sku = {variant.sku: variant for variant in summary.variants}

    assert by_sku[parent_variant.sku].sevdesk_state == "pending"
    assert by_sku[child_variant.sku].sevdesk_state == "synced"
    assert by_sku[child_variant.sku].wix_state == "synced"


def test_tags_are_aggregated_per_product(product_repo: ProductHubRepository) -> None:
    product, _variant = product_repo.create_product(sku="XW-1", name="A")
    tag = product_repo.get_or_create_tag(code="amazon", label="Amazon")
    product_repo.add_product_tag(product_id=product.id, tag_id=tag.id)
    product = product_repo.get_product(product.id)
    assert product is not None

    [summary] = build_parent_product_summaries(product_repo, [product])

    assert summary.tags == ["Amazon"]


def test_archived_products_excluded_from_list_products_by_default(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _pv = product_repo.create_product(sku="XW-1", name="A")
    child, _cv = product_repo.create_product(sku="XW-1-D", name="A")
    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])

    results = product_repo.list_products(ProductFilter())

    assert [p.id for p in results] == [parent.id]


def test_archived_products_included_when_explicitly_requested(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _pv = product_repo.create_product(sku="XW-1", name="A")
    child, _cv = product_repo.create_product(sku="XW-1-D", name="A")
    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])

    results = product_repo.list_products(ProductFilter(include_archived=True))

    assert {p.id for p in results} == {parent.id, child.id}


def test_search_by_variant_sku_finds_the_parent(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    parent, _pv = product_repo.create_product(sku="XW-102.5", name="Volksmusik #2 - Tuba in B")
    child, _cv = product_repo.create_product(sku="XW-102.5-D", name="Volksmusik #2 - Tuba in B")
    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])

    results = product_repo.list_products(ProductFilter(search="XW-102.5-D"))

    assert [p.id for p in results] == [parent.id]


def test_review_required_rolls_up_from_any_grouped_variant(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    """A grouped-away child's own review_required flag must still surface on the
    parent row - a reviewer shouldn't have to open every variant to notice one needs
    attention."""
    parent, _pv = product_repo.create_product(sku="XW-1", name="A")
    child, _cv = product_repo.create_product(sku="XW-1-D", name="A")
    product_repo.update_product(
        child.id, expected_row_version=child.row_version, attributes={"review_required": True}
    )
    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])
    refreshed_parent = product_repo.get_product(parent.id)
    assert refreshed_parent is not None

    [summary] = build_parent_product_summaries(product_repo, [refreshed_parent])

    assert summary.review_required is True


def test_isbn_prefers_isbn13_and_asins_are_aggregated_per_parent(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    """Unlike attributes (format/ensemble/...), grouping *reparents* product-scoped
    identifiers onto the parent (see grouping.py's reparent_identifier) - so after
    grouping, a child's own ASIN shows up as the *parent's* ASIN, not attributed to
    any one specific variant (the DB no longer records which row it came from)."""
    parent, _pv = product_repo.create_product(sku="XW-1", name="A")
    product_repo.add_identifier(product_id=parent.id, scheme="ISBN13", value="9780000000001", normalized_value="9780000000001")
    product_repo.add_identifier(product_id=parent.id, scheme="ISBN10", value="0000000001", normalized_value="0000000001")
    product_repo.add_identifier(product_id=parent.id, scheme="ASIN", value="B000TEST01", normalized_value="B000TEST01")
    child, _cv = product_repo.create_product(sku="XW-1-D", name="A")
    product_repo.add_identifier(product_id=child.id, scheme="ASIN", value="B000TEST02", normalized_value="B000TEST02")
    grouping.group_products_into_parent(parent_product_id=parent.id, child_product_ids=[child.id])
    refreshed_parent = product_repo.get_product(parent.id)
    assert refreshed_parent is not None

    [summary] = build_parent_product_summaries(product_repo, [refreshed_parent])

    assert summary.isbns == ["9780000000001"]
    assert set(summary.asins) == {"B000TEST01", "B000TEST02"}


def test_display_sku_is_the_products_own_sku_after_grouping(
    product_repo: ProductHubRepository, grouping: GroupingService
) -> None:
    """The parent's own Product.sku is always the canonical_variant's SKU by
    construction (create_product() gives a product and its sole variant the same SKU;
    grouping never renames the parent) - the common case needs no fallback logic."""
    parent, _pv = product_repo.create_product(sku="XW-6004", name="Himmelsthron")
    child_a, _ca = product_repo.create_product(sku="XW-6218", name="Himmelsthron [Böhmische Besetzung]")
    child_b, _cb = product_repo.create_product(sku="XW-6605", name="Himmelsthron [Musikkapelle]")
    grouping.group_products_into_parent(
        parent_product_id=parent.id, child_product_ids=[child_a.id, child_b.id]
    )
    refreshed_parent = product_repo.get_product(parent.id)
    assert refreshed_parent is not None

    [summary] = build_parent_product_summaries(product_repo, [refreshed_parent])

    assert summary.display_sku == "XW-6004"
    assert summary.variant_count == 3


def test_wix_error_sync_status_surfaces_as_error_state(product_repo: ProductHubRepository) -> None:
    product, _variant = product_repo.create_product(sku="XW-1", name="A")
    product_repo.create_channel_mapping(
        channel="wix",
        entity_type="product",
        internal_entity_id=product.id,
        external_id="handle-1",
        sync_status="error",
    )
    product = product_repo.get_product(product.id)
    assert product is not None

    [summary] = build_parent_product_summaries(product_repo, [product])

    assert summary.wix_state == "error"
