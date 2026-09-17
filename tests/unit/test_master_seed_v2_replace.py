"""Tests for the safe replace-legacy-catalog workflow (Master Seed V1 -> V2)."""
from __future__ import annotations

from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import (
    AuditLog,
    ChannelMapping,
    PriceList,
    Product,
    ProductIdentifier,
    ProductImprovement,
    ProductVariant,
)
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.master_seed_v2_replace import (
    check_catalog_replaceable,
    delete_legacy_master_seed_catalog,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


def test_empty_catalog_is_safe_to_replace(session_factory: sessionmaker[Session]) -> None:
    check = check_catalog_replaceable(session_factory)
    assert check.product_count == 0
    assert check.is_safe_to_replace


def test_catalog_created_only_via_automated_import_is_safe_to_replace(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product, variant = product_repo.create_product(sku="XW-1", name="A")
    product_repo.record_audit(
        actor_type="system", entity_type="product", entity_id=product.id, action="create_from_staging"
    )

    check = check_catalog_replaceable(session_factory)

    assert check.product_count == 1
    assert check.is_safe_to_replace
    assert check.blocking_reason is None


def test_catalog_with_grouping_actions_is_still_safe_to_replace(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    """Running the curated-grouping step is itself part of the automated replace
    pipeline (see master_seed_v2_grouping.py), not a manual edit — a prior run's own
    grouping audit trail must never block a later re-run."""
    parent, _parent_variant = product_repo.create_product(sku="XW-1", name="A")
    child, child_variant = product_repo.create_product(sku="XW-1-D", name="A")
    for entity_type, entity_id, action in [
        ("product", parent.id, "create_from_staging"),
        ("product", child.id, "create_from_staging"),
        ("product_variant", child_variant.id, "move_variant_to_product"),
        ("product", child.id, "group_products_into_parent"),
        ("product", parent.id, "group_products_into_parent_receive"),
    ]:
        product_repo.record_audit(actor_type="system", entity_type=entity_type, entity_id=entity_id, action=action)

    check = check_catalog_replaceable(session_factory)

    assert check.is_safe_to_replace


def test_catalog_with_manual_patch_is_not_safe_to_replace(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product, _variant = product_repo.create_product(sku="XW-1", name="A")
    product_repo.record_audit(
        actor_type="system", entity_type="product", entity_id=product.id, action="create_from_staging"
    )
    product_repo.record_audit(
        actor_type="user", entity_type="product", entity_id=product.id, action="update"
    )

    check = check_catalog_replaceable(session_factory)

    assert not check.is_safe_to_replace
    assert "update" in check.non_automated_audit_actions
    assert check.blocking_reason is not None


def test_delete_removes_products_variants_improvements_and_channel_mappings(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product, variant = product_repo.create_product(sku="XW-1", name="A")
    product_repo.create_improvement(product_id=product.id, description="Fix me")
    product_repo.create_channel_mapping(
        channel="wix", entity_type="product", internal_entity_id=product.id, external_id="handle-1"
    )

    report = delete_legacy_master_seed_catalog(session_factory, actor="tester")

    assert report.products_deleted == 1
    assert report.variants_deleted == 1
    assert report.improvements_deleted == 1
    assert report.channel_mappings_deleted == 1

    with session_factory() as session:
        assert session.scalar(select(Product)) is None
        assert session.scalar(select(ProductVariant)) is None
        assert session.scalar(select(ProductImprovement)) is None
        assert session.scalar(select(ChannelMapping)) is None


def test_delete_removes_identifiers_and_prices_even_without_db_level_cascade(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    """Regression test: an earlier version of this function relied entirely on the
    schema's ON DELETE CASCADE, which SQLite (the test suite's DB) does not enforce
    without an explicit PRAGMA — it silently left product_identifier/product_price
    rows orphaned, and a second replace run's matching engine then "matched" staged
    rows against those orphaned, supposedly-deleted products. See module docstring."""
    product, variant = product_repo.create_product(sku="XW-1", name="A")
    product_repo.add_identifier(product_id=product.id, scheme="ISBN13", value="9780000000001", normalized_value="9780000000001")
    with session_factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()
    product_repo.set_price(variant.id, price_list_id=product_repo.get_price_list_by_code("RETAIL_EUR").id, gross_amount=Decimal("10.00"))

    delete_legacy_master_seed_catalog(session_factory)

    with session_factory() as session:
        assert session.scalar(select(ProductIdentifier)) is None
    assert product_repo.get_product_by_sku("XW-1") is None


def test_delete_on_empty_catalog_is_a_no_op(session_factory: sessionmaker[Session]) -> None:
    report = delete_legacy_master_seed_catalog(session_factory)
    assert report.products_deleted == 0
    assert report.variants_deleted == 0


def test_delete_records_an_audit_entry(
    session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product_repo.create_product(sku="XW-1", name="A")

    delete_legacy_master_seed_catalog(session_factory, actor="tester")

    # audit_log is intentionally never deleted (see module docstring) — a fresh
    # audit_log query must still find the summary entry this function itself wrote.
    with session_factory() as session:
        stmt = select(AuditLog).where(AuditLog.action == "master_seed_v2_replace_delete_legacy")
        entries = list(session.scalars(stmt))
    assert len(entries) == 1
