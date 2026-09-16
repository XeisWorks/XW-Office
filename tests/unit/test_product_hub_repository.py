"""Tests for the XW Product Hub canonical schema (PR01): models + repository."""
from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import (
    PriceList,
    ProductIdentifier,
    ProductPrice,
    ProductSkuAlias,
    ProductVariant,
)
from xw_office.repositories.product_hub import (
    OptimisticLockError,
    ProductFilter,
    ProductHubRepository,
    normalize_sku,
    slugify,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


# -- create_product / default variant --------------------------------------------


def test_create_product_creates_exactly_one_default_variant(repo: ProductHubRepository) -> None:
    product, variant = repo.create_product(sku=" xw-001 ", name="Ohrwürmer #1")

    assert product.sku == "XW-001"
    assert variant.sku == "XW-001"
    assert variant.is_default is True
    assert variant.product_id == product.id

    variants = repo.list_variants(product.id)
    assert len(variants) == 1
    assert variants[0].id == variant.id


def test_create_product_normalizes_sku(repo: ProductHubRepository) -> None:
    _, variant = repo.create_product(sku="  xw-777\t", name="Test")
    assert variant.sku == "XW-777"
    assert normalize_sku("  xw-777\t") == "XW-777"


def test_create_product_duplicate_sku_raises_integrity_error(
    repo: ProductHubRepository,
) -> None:
    repo.create_product(sku="XW-100", name="First")
    with pytest.raises(IntegrityError):
        repo.create_product(sku="xw-100", name="Duplicate different case")


def test_slug_uniqueness_auto_suffix(repo: ProductHubRepository) -> None:
    product_a, _ = repo.create_product(sku="XW-200", name="Ohrwürmer")
    product_b, _ = repo.create_product(sku="XW-201", name="Ohrwürmer")

    assert product_a.slug == "ohrwurmer" or product_a.slug == slugify("Ohrwürmer")
    assert product_b.slug != product_a.slug
    assert product_b.slug.startswith(product_a.slug)


# -- SKU resolution -----------------------------------------------------------------


def test_resolve_sku_is_case_and_whitespace_insensitive(repo: ProductHubRepository) -> None:
    product, variant = repo.create_product(sku="XW-300", name="Test")

    resolved = repo.resolve_sku("  xw-300 ")
    assert resolved is not None
    assert resolved.product.id == product.id
    assert resolved.variant.id == variant.id


def test_resolve_sku_unknown_returns_none(repo: ProductHubRepository) -> None:
    assert repo.resolve_sku("does-not-exist") is None
    assert repo.resolve_sku("") is None


def test_resolve_sku_via_legacy_alias(
    repo: ProductHubRepository, session_factory: sessionmaker[Session]
) -> None:
    product, variant = repo.create_product(sku="XW-400", name="Test")
    with session_factory() as session:
        session.add(
            ProductSkuAlias(
                product_id=product.id,
                alias_sku="LEGACY-400",
                source="legacy",
                variant_id=variant.id,
            )
        )
        session.commit()

    resolved = repo.resolve_sku("legacy-400")
    assert resolved is not None
    assert resolved.product.id == product.id
    assert resolved.variant.id == variant.id


def test_resolve_sku_via_alias_without_variant_link_falls_back_to_default(
    repo: ProductHubRepository, session_factory: sessionmaker[Session]
) -> None:
    product, variant = repo.create_product(sku="XW-401", name="Test")
    with session_factory() as session:
        session.add(ProductSkuAlias(product_id=product.id, alias_sku="OLD-401", source="legacy"))
        session.commit()

    resolved = repo.resolve_sku("OLD-401")
    assert resolved is not None
    assert resolved.variant.id == variant.id


# -- default variant invariant --------------------------------------------------------


def test_set_default_variant_unsets_previous_default(
    repo: ProductHubRepository, session_factory: sessionmaker[Session]
) -> None:
    product, first_variant = repo.create_product(sku="XW-500", name="Multi")
    with session_factory() as session:
        second_variant = ProductVariant(
            id=uuid.uuid4(),
            product_id=product.id,
            sku="XW-500-B",
            name="Variant B",
            is_default=False,
            active=True,
            stock_enabled=True,
            option_values={},
            attributes={},
        )
        session.add(second_variant)
        session.commit()
        second_variant_id = second_variant.id

    repo.set_default_variant(second_variant_id)

    with session_factory() as session:
        refreshed_first = session.get(type(first_variant), first_variant.id)
        refreshed_second = session.get(type(first_variant), second_variant_id)
        assert refreshed_first is not None and refreshed_first.is_default is False
        assert refreshed_second is not None and refreshed_second.is_default is True

    default_variant = repo.get_default_variant(product.id)
    assert default_variant is not None
    assert default_variant.id == second_variant_id


# -- optimistic locking ---------------------------------------------------------------


def test_update_product_succeeds_and_bumps_row_version(repo: ProductHubRepository) -> None:
    product, _ = repo.create_product(sku="XW-600", name="Old Name")
    assert product.row_version == 1

    updated = repo.update_product(product.id, expected_row_version=1, name="New Name")

    assert updated.name == "New Name"
    assert updated.row_version == 2


def test_update_product_stale_row_version_raises(repo: ProductHubRepository) -> None:
    product, _ = repo.create_product(sku="XW-601", name="Old Name")

    with pytest.raises(OptimisticLockError):
        repo.update_product(product.id, expected_row_version=999, name="New Name")


def test_update_product_unknown_field_raises(repo: ProductHubRepository) -> None:
    product, _ = repo.create_product(sku="XW-602", name="Old Name")
    with pytest.raises(ValueError):
        repo.update_product(product.id, expected_row_version=1, not_a_real_field="x")


# -- identifiers ------------------------------------------------------------------------


def test_identifier_unique_scheme_and_value(
    repo: ProductHubRepository, session_factory: sessionmaker[Session]
) -> None:
    product, _ = repo.create_product(sku="XW-700", name="Book")
    repo.add_identifier(
        product_id=product.id, scheme="ISBN13", value="978-3-16-148410-0", normalized_value="9783161484100"
    )
    with pytest.raises(IntegrityError):
        repo.add_identifier(
            product_id=product.id,
            scheme="ISBN13",
            value="978-3-16-148410-0 (dup)",
            normalized_value="9783161484100",
        )


def test_identifier_requires_exactly_one_owner(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(
            ProductIdentifier(
                id=uuid.uuid4(),
                product_id=None,
                variant_id=None,
                scheme="EAN",
                value="4006381333931",
                normalized_value="4006381333931",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_identifier_rejects_both_owners_set(
    repo: ProductHubRepository, session_factory: sessionmaker[Session]
) -> None:
    product, variant = repo.create_product(sku="XW-701", name="Book")
    with session_factory() as session:
        session.add(
            ProductIdentifier(
                id=uuid.uuid4(),
                product_id=product.id,
                variant_id=variant.id,
                scheme="ASIN",
                value="B000000000",
                normalized_value="B000000000",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


# -- money uses Decimal, never float ------------------------------------------------------


def test_product_price_amounts_are_decimal_not_float(
    repo: ProductHubRepository, session_factory: sessionmaker[Session]
) -> None:
    product, variant = repo.create_product(sku="XW-800", name="Priced")
    with session_factory() as session:
        price_list = PriceList(
            id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR", currency="EUR"
        )
        session.add(price_list)
        session.flush()
        price = ProductPrice(
            id=uuid.uuid4(),
            variant_id=variant.id,
            price_list_id=price_list.id,
            currency="EUR",
            net_amount=Decimal("23.3600"),
            gross_amount=Decimal("24.9900"),
            tax_rate=Decimal("7.0000"),
            valid_from=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(price)
        session.commit()
        price_id = price.id

    with session_factory() as session:
        stored = session.get(ProductPrice, price_id)
        assert stored is not None
        assert isinstance(stored.net_amount, Decimal)
        assert isinstance(stored.gross_amount, Decimal)
        assert stored.gross_amount == Decimal("24.9900")


# -- listing / filters ----------------------------------------------------------------------


def test_list_products_filters_by_status_and_active(repo: ProductHubRepository) -> None:
    live_product, _ = repo.create_product(sku="XW-900", name="Live One", status="live")
    draft_product, _ = repo.create_product(sku="XW-901", name="Draft One", status="draft")

    live_results = repo.list_products(ProductFilter(status="live"))
    assert [p.id for p in live_results] == [live_product.id]

    all_results = repo.list_products()
    assert {p.id for p in all_results} == {live_product.id, draft_product.id}


def test_list_products_search_matches_name_case_insensitively(
    repo: ProductHubRepository,
) -> None:
    product, _ = repo.create_product(sku="XW-902", name="Blechhaufen Marsch")
    repo.create_product(sku="XW-903", name="Unrelated")

    results = repo.list_products(ProductFilter(search="blechhaufen"))
    assert [p.id for p in results] == [product.id]
