"""Tests for the dealer sharing service (PR12)."""
from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_sharing import SharingRepository
from xw_office.services.product_hub.sharing import (
    InvalidFieldWhitelistError,
    RateLimitExceededError,
    ShareInactiveError,
    ShareNotFoundError,
    SharingService,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.add(PriceList(id=uuid.uuid4(), code="B2B_EUR", name="B2B EUR"))
        session.commit()
    return factory


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


@pytest.fixture
def service(session_factory: sessionmaker[Session], product_repo: ProductHubRepository) -> SharingService:
    return SharingService(product_repo, SharingRepository(session_factory))


def _seed_b2b_live_product(product_repo: ProductHubRepository, *, sku: str = "XW-3000"):
    product, variant = product_repo.create_product(
        sku=sku, name="Katalog Produkt", status="live", short_description="Kurzbeschreibung"
    )
    tag = product_repo.get_or_create_tag(code="B2B", label="B2B")
    product_repo.add_product_tag(product_id=product.id, tag_id=tag.id)
    product_repo.add_identifier(
        scheme="ISBN13", value="978-3-000000-0", normalized_value="9783000000", product_id=product.id
    )
    product_repo.add_asset(
        product_id=product.id, role="COVER", storage_kind="EXTERNAL_URL", uri="https://x/cover.jpg"
    )
    retail = product_repo.get_price_list_by_code("RETAIL_EUR")
    b2b = product_repo.get_price_list_by_code("B2B_EUR")
    assert retail is not None and b2b is not None
    product_repo.set_price(variant.id, price_list_id=retail.id, gross_amount=Decimal("29.99"))
    product_repo.set_price(variant.id, price_list_id=b2b.id, gross_amount=Decimal("19.99"))
    return product, variant


# -- create_share -------------------------------------------------------------------


def test_create_share_returns_plaintext_token_once_and_stores_only_hash(
    service: SharingService, session_factory: sessionmaker[Session]
) -> None:
    share, token = service.create_share(title="Sommerkatalog")

    assert len(token) > 20
    assert share.token_hash != token
    assert len(share.token_hash) == 64  # sha256 hex

    with session_factory() as session:
        from xw_office.models.product_hub_sharing import SharedCatalogView

        row = session.get(SharedCatalogView, share.id)
        assert row is not None
        assert row.token_hash == share.token_hash


def test_create_share_rejects_disallowed_field(service: SharingService) -> None:
    with pytest.raises(InvalidFieldWhitelistError):
        service.create_share(title="x", field_whitelist=["sku", "purchase_cost"])


def test_create_share_unknown_price_list_code_raises(service: SharingService) -> None:
    with pytest.raises(KeyError):
        service.create_share(title="x", price_list_code="DOES-NOT-EXIST")


# -- resolve_token --------------------------------------------------------------------


def test_resolve_token_success(service: SharingService) -> None:
    _share, token = service.create_share(title="x")
    resolved = service.resolve_token(token)
    assert resolved.title == "x"
    assert resolved.last_access_at is not None


def test_resolve_token_unknown_raises(service: SharingService) -> None:
    with pytest.raises(ShareNotFoundError):
        service.resolve_token("not-a-real-token")


def test_resolve_token_revoked_raises(service: SharingService) -> None:
    share, token = service.create_share(title="x")
    service.revoke(share.id)
    with pytest.raises(ShareInactiveError):
        service.resolve_token(token)


def test_resolve_token_expired_raises(
    service: SharingService, session_factory: sessionmaker[Session]
) -> None:
    share, token = service.create_share(title="x")
    with session_factory() as session:
        from xw_office.models.product_hub_sharing import SharedCatalogView

        row = session.get(SharedCatalogView, share.id)
        assert row is not None
        row.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        session.commit()

    with pytest.raises(ShareInactiveError):
        service.resolve_token(token)


def test_resolve_token_rate_limited(service: SharingService) -> None:
    _share, token = service.create_share(title="x")
    # exhaust the window (60 req/min default)
    for _ in range(60):
        service.resolve_token(token)
    with pytest.raises(RateLimitExceededError):
        service.resolve_token(token)


# -- query_catalog --------------------------------------------------------------------


def test_query_catalog_default_filter_and_fields(
    service: SharingService, product_repo: ProductHubRepository
) -> None:
    _seed_b2b_live_product(product_repo)
    product_repo.create_product(sku="XW-3001", name="Nicht B2B", status="live")  # no B2B tag
    product_repo.create_product(sku="XW-3002", name="Draft", status="draft")  # wrong status

    share, _token = service.create_share(title="x")
    rows = service.query_catalog(share)

    assert len(rows) == 1
    row = rows[0]
    assert row["sku"] == "XW-3000"
    assert row["name"] == "Katalog Produkt"
    assert row["isbn"] == "978-3-000000-0"
    assert row["cover_url"] == "https://x/cover.jpg"
    assert row["price_uvp"] == "29.99"
    assert row["price_b2b"] == "19.99"
    assert row["available"] is True
    assert row["description"] == "Kurzbeschreibung"


def test_query_catalog_respects_field_whitelist(
    service: SharingService, product_repo: ProductHubRepository
) -> None:
    _seed_b2b_live_product(product_repo)
    share, _token = service.create_share(title="x", field_whitelist=["sku", "name"])

    rows = service.query_catalog(share)

    assert rows == [{"sku": "XW-3000", "name": "Katalog Produkt"}]


def test_query_catalog_never_exposes_network_path_cover(
    service: SharingService, product_repo: ProductHubRepository
) -> None:
    product, _variant = _seed_b2b_live_product(product_repo, sku="XW-3003")
    product_repo.add_asset(
        product_id=product.id,
        role="COVER",
        storage_kind="NETWORK_PATH",
        uri="\\\\fileserver\\covers\\secret.jpg",
        sort_order=0,
    )
    share, _token = service.create_share(title="x")

    rows = service.query_catalog(share)
    row = next(r for r in rows if r["sku"] == "XW-3003")
    # the EXTERNAL_URL cover from _seed_b2b_live_product should win, never the network path
    assert row["cover_url"] == "https://x/cover.jpg"


def test_query_catalog_unavailable_when_default_variant_inactive(
    service: SharingService, product_repo: ProductHubRepository
) -> None:
    product, variant = _seed_b2b_live_product(product_repo, sku="XW-3004")
    product_repo.update_variant(variant.id, expected_row_version=1, active=False)

    share, _token = service.create_share(title="x")
    rows = service.query_catalog(share)
    row = next(r for r in rows if r["sku"] == "XW-3004")
    assert row["available"] is False


def test_query_catalog_uses_custom_price_list(
    service: SharingService, product_repo: ProductHubRepository
) -> None:
    _seed_b2b_live_product(product_repo)
    custom = product_repo.get_price_list_by_code("B2B_EUR")
    assert custom is not None
    share, _token = service.create_share(title="x", price_list_code="B2B_EUR")

    rows = service.query_catalog(share)
    assert rows[0]["price_b2b"] == "19.99"


def test_record_export(service: SharingService, product_repo: ProductHubRepository) -> None:
    _seed_b2b_live_product(product_repo)
    share, _token = service.create_share(title="x")
    rows = service.query_catalog(share)

    entry = service.record_export(share, export_format="csv", row_count=len(rows))

    assert entry.shared_view_id == share.id
    assert entry.format == "csv"
    assert entry.row_count == 1
