"""Tests for the reconciled master-seed CSV importer (2026-09-17)."""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.models.product_hub import PriceList
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.product_hub.import_commit import ImportCommitService
from xw_office.services.product_hub.master_seed_import import MasterSeedImporter

_COLUMNS = [
    "sku", "parent_sku", "product_group_id", "group_key", "grouping_confidence",
    "status", "record_state", "active", "brand", "catalog_line", "category_primary",
    "series", "series_code", "volume", "work_title", "product_kind", "product_type",
    "instrument", "voice", "transposition", "register", "clef", "ensemble", "scoring",
    "voice_count", "format", "title_full", "title_short", "code_short", "description",
    "content_status", "content_source", "bullet_point_1", "bullet_point_2",
    "bullet_point_3", "bullet_point_4", "bullet_point_5", "tags", "price_net",
    "vat_percent", "price_gross", "currency", "price_source", "stock_on_hand",
    "stock_enabled", "weight_grams", "isbn13", "isbn10", "ean", "asin", "asin_source",
    "asin_verified", "fnsku", "fnsku_status", "amazon_seller_sku", "amazon_status",
    "amazon_product_type", "amazon_product_id_type", "amazon_product_id",
    "amazon_fulfillment", "amazon_quantity", "amazon_title", "amazon_item_name",
    "amazon_description_html", "wix_handle_id", "wix_visible", "wix_collections",
    "wix_media_urls", "wix_description_html", "erp_category", "source_title_xlsx",
    "source_title_wix", "source_title_erp", "title_source", "source_of_truth",
    "sot_row", "conflict_flags", "conflict_notes",
]


def _row(**overrides: str) -> dict[str, str]:
    base = {col: "" for col in _COLUMNS}
    base.update(overrides)
    return base


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def import_repo(session_factory: sessionmaker[Session]) -> ProductHubImportRepository:
    return ProductHubImportRepository(session_factory)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


def test_run_stages_products_with_core_fields(
    tmp_path: Path, import_repo: ProductHubImportRepository
) -> None:
    csv_path = tmp_path / "seed.csv"
    _write_csv(
        csv_path,
        [
            _row(
                sku="XW-9001",
                title_full="Testtitel [Kleine Besetzung]",
                status="live",
                record_state="ACTIVE",
                active="true",
                brand="XeisWorks",
                category_primary="TANZLMUSI",
                product_type="physical",
                price_net="20.00",
                vat_percent="10",
                price_gross="22.00",
                wix_handle_id="wix-abc-123",
                content_status="SOURCE",
            )
        ],
    )
    importer = MasterSeedImporter(import_repo=import_repo)

    report = importer.run(csv_path)

    assert report.rows_staged == 1
    assert report.errors == []
    staged = import_repo.list_staging_products()
    assert len(staged) == 1
    row = staged[0]
    assert row.sku == "XW-9001"
    assert row.name == "Testtitel [Kleine Besetzung]"
    assert row.normalized_fields["status"] == "live"
    assert row.normalized_fields["active"] is True
    assert row.normalized_fields["brutto"] == "22.00"
    assert row.normalized_fields["netto"] == "20.00"
    assert row.normalized_fields["wix_handle_id"] == "wix-abc-123"
    assert row.normalized_fields["not_for_sale"] is False


def test_run_stages_identifiers(tmp_path: Path, import_repo: ProductHubImportRepository) -> None:
    csv_path = tmp_path / "seed.csv"
    _write_csv(
        csv_path,
        [
            _row(
                sku="XW-9002",
                title_full="Buchprodukt",
                isbn13="9783000000001",
                asin="B000TEST01",
                fnsku="X001TEST",
            )
        ],
    )
    importer = MasterSeedImporter(import_repo=import_repo)
    report = importer.run(csv_path)

    assert report.identifiers_staged == 3
    staged = import_repo.list_staging_products()[0]
    identifiers = {row.scheme: row.value for row in import_repo.list_identifiers(staged.id)}
    assert identifiers == {"ISBN13": "9783000000001", "ASIN": "B000TEST01", "FNSKU": "X001TEST"}


def test_run_tags_external_only_as_not_for_sale(
    tmp_path: Path, import_repo: ProductHubImportRepository
) -> None:
    csv_path = tmp_path / "seed.csv"
    _write_csv(
        csv_path,
        [_row(sku="XW-001", title_full="Versand", record_state="EXTERNAL_ONLY", tags="Versand")],
    )
    importer = MasterSeedImporter(import_repo=import_repo)
    report = importer.run(csv_path)

    assert report.not_for_sale_count == 1
    staged = import_repo.list_staging_products()[0]
    assert "Nicht zum Verkauf" in staged.normalized_fields["suggested_tags"]
    assert "Versand" in staged.normalized_fields["suggested_tags"]


def test_run_counts_auto_draft_content(
    tmp_path: Path, import_repo: ProductHubImportRepository
) -> None:
    csv_path = tmp_path / "seed.csv"
    _write_csv(
        csv_path,
        [
            _row(sku="XW-9003", title_full="A", content_status="AUTO_DRAFT"),
            _row(sku="XW-9004", title_full="B", content_status="SOURCE"),
        ],
    )
    importer = MasterSeedImporter(import_repo=import_repo)
    report = importer.run(csv_path)

    assert report.rows_staged == 2
    assert report.auto_draft_content_count == 1


# -- commit-time enrichment (import_commit.py's master_seed branch) -------------------


@pytest.fixture
def commit_service(session_factory: sessionmaker[Session]) -> ImportCommitService:
    return ImportCommitService(session_factory)


def _seed_and_stage(
    tmp_path: Path, import_repo: ProductHubImportRepository, **overrides: str
) -> tuple[ProductHubImportRepository, str]:
    csv_path = tmp_path / "seed.csv"
    _write_csv(csv_path, [_row(**overrides)])
    MasterSeedImporter(import_repo=import_repo).run(csv_path)
    staged = import_repo.list_staging_products()[0]
    return import_repo, str(staged.id)


def test_commit_creates_wix_channel_mapping_when_handle_present(
    tmp_path: Path,
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    _import_repo, staged_id = _seed_and_stage(
        tmp_path, import_repo, sku="XW-9005", title_full="Mit Wix", wix_handle_id="wix-handle-1"
    )

    product = commit_service.create_from_staging(uuid.UUID(staged_id))

    mappings = product_repo.list_channel_mappings(entity_type="product", internal_entity_id=product.id)
    assert len(mappings) == 1
    assert mappings[0].channel == "wix"
    assert mappings[0].external_id == "wix-handle-1"


def test_commit_creates_no_wix_mapping_for_external_only_row(
    tmp_path: Path,
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    _import_repo, staged_id = _seed_and_stage(
        tmp_path, import_repo, sku="XW-002", title_full="Gutschrift", record_state="EXTERNAL_ONLY"
    )

    product = commit_service.create_from_staging(uuid.UUID(staged_id))

    assert product_repo.list_channel_mappings(entity_type="product", internal_entity_id=product.id) == []
    tags = {link.tag_id for link in product_repo.list_product_tags(product.id)}
    assert len(tags) == 1  # "Nicht zum Verkauf"


def test_commit_flags_auto_draft_content_as_improvement(
    tmp_path: Path,
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    _import_repo, staged_id = _seed_and_stage(
        tmp_path, import_repo, sku="XW-9006", title_full="Auto Draft", content_status="AUTO_DRAFT"
    )

    product = commit_service.create_from_staging(uuid.UUID(staged_id))

    improvements = product_repo.list_improvements(product.id)
    assert len(improvements) == 1
    assert improvements[0].source == "master_seed_import"
    assert improvements[0].status == "open"


def test_commit_sets_retail_price_with_ten_percent_vat(
    tmp_path: Path,
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(PriceList(id=uuid.uuid4(), code="RETAIL_EUR", name="Retail EUR"))
        session.commit()

    _import_repo, staged_id = _seed_and_stage(
        tmp_path,
        import_repo,
        sku="XW-9007",
        title_full="Preisprodukt",
        price_net="20.00",
        price_gross="22.00",
        vat_percent="10",
    )

    product = commit_service.create_from_staging(uuid.UUID(staged_id))

    variant = product_repo.get_default_variant(product.id)
    assert variant is not None
    prices = product_repo.list_prices(variant.id)
    assert len(prices) == 1
    assert prices[0].gross_amount == Decimal("22.00")
    assert prices[0].net_amount == Decimal("20.00")
    assert prices[0].tax_rate == Decimal("0.10")


def test_commit_merges_extra_attributes(
    tmp_path: Path,
    import_repo: ProductHubImportRepository,
    product_repo: ProductHubRepository,
    commit_service: ImportCommitService,
) -> None:
    _import_repo, staged_id = _seed_and_stage(
        tmp_path,
        import_repo,
        sku="XW-9008",
        title_full="Attribut-Produkt",
        title_short="Attr.",
        code_short="ATTR",
        ensemble="Kleine Besetzung",
        group_key="grp-1",
        bullet_point_1="Erstes Merkmal",
    )

    product = commit_service.create_from_staging(uuid.UUID(staged_id))

    refreshed = product_repo.get_product(product.id)
    assert refreshed is not None
    assert refreshed.attributes["title_short"] == "Attr."
    assert refreshed.attributes["code_short"] == "ATTR"
    assert refreshed.attributes["group_key"] == "grp-1"
    assert refreshed.attributes["bullet_points"] == ["Erstes Merkmal"]
    assert refreshed.attributes["music_attributes"] == {"ensemble": "Kleine Besetzung"}
