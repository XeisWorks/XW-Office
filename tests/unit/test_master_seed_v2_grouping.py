"""Tests for applying the Master Seed V2 curated grouping to already-flat products."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.master_seed_v2_grouping import (
    apply_master_seed_v2_grouping,
    plan_groups_from_master_seed,
)

_COLUMNS = ["sku", "product_group_id", "canonical_variant", "variant_role", "title_full", "parent_sku"]


def _row(**overrides: str) -> dict[str, str]:
    base = {col: "" for col in _COLUMNS}
    base.update(overrides)
    return base


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


# -- plan_groups_from_master_seed (pure) ---------------------------------------------


def test_plan_skips_single_row_groups() -> None:
    rows = [_row(sku="XW-1", product_group_id="g1", canonical_variant="true")]
    assert plan_groups_from_master_seed(rows) == []


def test_plan_skips_rows_without_group_id() -> None:
    rows = [_row(sku="XW-1"), _row(sku="XW-2")]
    assert plan_groups_from_master_seed(rows) == []


def test_plan_builds_canonical_plus_children() -> None:
    rows = [
        _row(sku="XW-102.5", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-102.5-D", product_group_id="g1", canonical_variant="false"),
    ]
    plans = plan_groups_from_master_seed(rows)
    assert len(plans) == 1
    assert plans[0].canonical_sku == "XW-102.5"
    assert plans[0].child_skus == ["XW-102.5-D"]


def test_plan_skips_group_without_exactly_one_canonical() -> None:
    rows = [
        _row(sku="XW-1", product_group_id="g1", canonical_variant="false"),
        _row(sku="XW-2", product_group_id="g1", canonical_variant="false"),
    ]
    assert plan_groups_from_master_seed(rows) == []


def test_plan_accepts_agreeing_parent_sku() -> None:
    rows = [
        _row(sku="XW-1", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-2", product_group_id="g1", canonical_variant="false", parent_sku="XW-1"),
    ]
    plans = plan_groups_from_master_seed(rows)
    assert len(plans) == 1
    assert plans[0].canonical_sku == "XW-1"


def test_plan_skips_group_where_parent_sku_disagrees_with_canonical_variant() -> None:
    rows = [
        _row(sku="XW-1", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-2", product_group_id="g1", canonical_variant="false", parent_sku="XW-999"),
    ]
    assert plan_groups_from_master_seed(rows) == []


# -- apply_master_seed_v2_grouping (DB) ----------------------------------------------


def test_apply_groups_format_variant_into_canonical_product(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    parent, _ = product_repo.create_product(sku="XW-102.5", name="Volksmusik #2 - Tuba in B")
    child, child_variant = product_repo.create_product(sku="XW-102.5-D", name="Volksmusik #2 - Tuba in B")

    rows = [
        _row(sku="XW-102.5", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-102.5-D", product_group_id="g1", canonical_variant="false"),
    ]
    report = apply_master_seed_v2_grouping(session_factory, rows, actor="tester")

    assert report.groups_considered == 1
    assert report.groups_applied == 1
    assert report.variants_moved == 1
    assert report.products_archived == 1
    assert report.conflicts == []
    assert report.errors == []

    moved_variant = product_repo.get_variant(child_variant.id)
    assert moved_variant is not None
    assert moved_variant.product_id == parent.id
    archived_child = product_repo.get_product(child.id)
    assert archived_child is not None
    assert archived_child.active is False


def test_apply_is_idempotent_on_rerun(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product_repo.create_product(sku="XW-102.5", name="Volksmusik #2 - Tuba in B")
    product_repo.create_product(sku="XW-102.5-D", name="Volksmusik #2 - Tuba in B")
    rows = [
        _row(sku="XW-102.5", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-102.5-D", product_group_id="g1", canonical_variant="false"),
    ]

    first = apply_master_seed_v2_grouping(session_factory, rows)
    second = apply_master_seed_v2_grouping(session_factory, rows)

    assert first.groups_applied == 1
    assert second.groups_applied == 0
    assert second.groups_skipped_single_row == 1  # child already resolves to the parent
    assert second.errors == []


def test_apply_skips_group_with_channel_mapping_conflict(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    parent, _ = product_repo.create_product(sku="XW-1", name="Basis")
    child, _ = product_repo.create_product(sku="XW-1-D", name="Basis")
    product_repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=parent.id, external_id="handle-parent"
    )
    product_repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=child.id, external_id="handle-child"
    )
    rows = [
        _row(sku="XW-1", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-1-D", product_group_id="g1", canonical_variant="false"),
    ]

    report = apply_master_seed_v2_grouping(session_factory, rows)

    assert report.groups_applied == 0
    assert len(report.conflicts) == 1
    # nothing was written — the child product is still its own, un-archived product
    refreshed_child = product_repo.get_product(child.id)
    assert refreshed_child is not None
    assert refreshed_child.active is True


def test_apply_reports_error_for_unresolvable_child_sku(session_factory: sessionmaker[Session], product_repo: ProductHubRepository) -> None:
    product_repo.create_product(sku="XW-1", name="Basis")
    rows = [
        _row(sku="XW-1", product_group_id="g1", canonical_variant="true"),
        _row(sku="XW-DOES-NOT-EXIST", product_group_id="g1", canonical_variant="false"),
    ]

    report = apply_master_seed_v2_grouping(session_factory, rows)

    assert report.groups_applied == 0
    assert len(report.errors) == 1
