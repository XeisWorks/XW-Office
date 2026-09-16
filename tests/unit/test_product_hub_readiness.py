"""Tests for the channel readiness calculation (PR07)."""
from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList, ProductAsset, ProductImprovement, ProductPrice, PrintRule
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.readiness import build_readiness_summary, evaluate_product_readiness


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


def test_bare_product_is_not_ready_for_any_channel(repo: ProductHubRepository) -> None:
    product, _ = repo.create_product(sku="XW-1", name="Bare")

    readiness = evaluate_product_readiness(repo, product)

    assert readiness.wix_ready is False
    assert readiness.b2b_ready is False
    assert readiness.print_ready is False
    assert readiness.sevdesk_ready is False
    assert "Cover" in readiness.wix_missing
    assert "Retail-Preis" in readiness.wix_missing


def test_wix_ready_once_cover_description_category_and_price_present(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, variant = repo.create_product(sku="XW-2", name="Vollständig", description="Eine Beschreibung")
    repo.add_asset(product_id=product.id, role="COVER", storage_kind="EXTERNAL_URL", uri="https://x/cover.jpg")
    category = repo.get_or_create_category(code="tanzlmusi", name="Tanzlmusi")
    repo.add_product_category(product_id=product.id, category_id=category.id)

    with session_factory() as session:
        price_list = PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR", currency="EUR")
        session.add(price_list)
        session.flush()
        session.add(
            ProductPrice(
                id=uuid.uuid4(),
                variant_id=variant.id,
                price_list_id=price_list.id,
                currency="EUR",
                gross_amount=24.9,
                valid_from=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        session.commit()

    readiness = evaluate_product_readiness(repo, product)

    assert readiness.wix_ready is True
    assert readiness.wix_missing == []


def test_b2b_ready_requires_tag_and_b2b_price(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, variant = repo.create_product(sku="XW-3", name="B2B Test", description="x")
    repo.add_asset(product_id=product.id, role="COVER", storage_kind="EXTERNAL_URL", uri="https://x/c.jpg")

    readiness_without_tag = evaluate_product_readiness(repo, product)
    assert readiness_without_tag.b2b_ready is False
    assert "Tag B2B" in readiness_without_tag.b2b_missing

    tag = repo.get_or_create_tag(code="b2b", label="B2B")
    repo.add_product_tag(product_id=product.id, tag_id=tag.id)

    readiness_without_price = evaluate_product_readiness(repo, product)
    assert readiness_without_price.b2b_ready is False
    assert "Händlerpreis" in readiness_without_price.b2b_missing

    with session_factory() as session:
        price_list = PriceList(id=uuid.uuid4(), code="B2B_EUR", name="B2B EUR", currency="EUR")
        session.add(price_list)
        session.flush()
        session.add(
            ProductPrice(
                id=uuid.uuid4(),
                variant_id=variant.id,
                price_list_id=price_list.id,
                currency="EUR",
                net_amount=15.0,
                valid_from=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        session.commit()

    readiness_ready = evaluate_product_readiness(repo, product)
    assert readiness_ready.b2b_ready is True


def test_print_ready_requires_healthy_asset_and_print_rule(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    product, variant = repo.create_product(sku="XW-4", name="Print Test")
    asset = repo.add_asset(
        product_id=product.id,
        variant_id=variant.id,
        role="PRINT_PDF",
        storage_kind="NETWORK_PATH",
        uri=r"\\server\share\file.pdf",
    )

    not_ready = evaluate_product_readiness(repo, product)
    assert not_ready.print_ready is False
    assert "Produktions-PDF (Health ok)" in not_ready.print_missing

    with session_factory() as session:
        stored_asset = session.get(ProductAsset, asset.id)
        assert stored_asset is not None
        stored_asset.health_status = "ok"
        session.add(PrintRule(id=uuid.uuid4(), variant_id=variant.id, print_profile_id="noten_duplex"))
        session.commit()

    ready = evaluate_product_readiness(repo, product)
    assert ready.print_ready is True


def test_sevdesk_ready_requires_channel_mapping(repo: ProductHubRepository) -> None:
    product, _ = repo.create_product(sku="XW-5", name="Sevdesk Test")

    not_ready = evaluate_product_readiness(repo, product)
    assert not_ready.sevdesk_ready is False

    repo.create_channel_mapping(
        channel="sevdesk", entity_type="product", internal_entity_id=product.id, external_id="part-1"
    )

    ready = evaluate_product_readiness(repo, product)
    assert ready.sevdesk_ready is True


def test_readiness_check_never_writes_a_tag(repo: ProductHubRepository) -> None:
    """A readiness *check* must have zero side effects, even for a tag that doesn't exist yet."""
    product, _ = repo.create_product(sku="XW-6", name="No Side Effects")

    evaluate_product_readiness(repo, product)

    assert repo.find_tag_by_code("b2b") is None


def test_build_readiness_summary_aggregates_across_products(
    session_factory: sessionmaker[Session], repo: ProductHubRepository
) -> None:
    ready_product, _ = repo.create_product(sku="XW-10", name="Bereit", description="x")
    repo.add_asset(product_id=ready_product.id, role="COVER", storage_kind="EXTERNAL_URL", uri="https://x/c.jpg")
    not_ready_product, _ = repo.create_product(sku="XW-11", name="Nicht bereit")

    with session_factory() as session:
        session.add(
            ProductImprovement(
                id=uuid.uuid4(),
                product_id=not_ready_product.id,
                description="Tippfehler auf Seite 2",
                status="open",
            )
        )
        session.commit()

    summary = build_readiness_summary(repo, [ready_product, not_ready_product])

    assert summary.total_products == 2
    assert summary.missing_cover == 1
    assert summary.open_improvements == 1
