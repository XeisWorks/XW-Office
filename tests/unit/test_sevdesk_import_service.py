"""Tests for the sevdesk -> Product Hub staging importer (PR04).

Uses a fixture-based fake PartClient (no network) per the build-plan's required
scenarios: physical/digital (stockEnabled), category mapping, empty-SKU handling,
and stock parsing.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.product_hub.sevdesk_import import SevdeskPartImporter


class _FakePartsClient:
    def __init__(self, raw_parts: list[dict[str, Any]]) -> None:
        self._raw_parts = raw_parts

    def fetch_parts_raw(self, *, max_pages: int = 20) -> list[dict[str, Any]]:
        return list(self._raw_parts)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def import_repo(session_factory: sessionmaker[Session]) -> ProductHubImportRepository:
    return ProductHubImportRepository(session_factory)


def test_import_physical_part_stages_stock(import_repo: ProductHubImportRepository) -> None:
    raw = {
        "id": "500",
        "partNumber": "XW-500",
        "name": "Etuede A",
        "stock": "12",
        "stockEnabled": "1",
        "taxRate": "20",
    }
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    report = importer.run()

    assert report.parts_seen == 1
    assert report.parts_staged == 1
    staged = import_repo.list_staging_products()[0]
    assert staged.sku == "XW-500"
    assert staged.normalized_fields["stock_enabled"] is True

    inventory = import_repo.list_inventory(staged.id)
    assert inventory[0].quantity == 12
    assert inventory[0].stock_enabled is True
    assert inventory[0].location_external_id == "sevdesk"


def test_import_digital_part_marks_stock_disabled(import_repo: ProductHubImportRepository) -> None:
    raw = {"id": "501", "partNumber": "XW-DIGI", "name": "Digital Heft", "stockEnabled": "0"}
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    importer.run()

    staged = import_repo.list_staging_products()[0]
    assert staged.normalized_fields["stock_enabled"] is False
    inventory = import_repo.list_inventory(staged.id)
    assert inventory[0].stock_enabled is False


def test_import_maps_category(import_repo: ProductHubImportRepository) -> None:
    raw = {
        "id": "502",
        "partNumber": "XW-502",
        "name": "Kategorisiert",
        "category": {"id": "CAT-7", "name": "MusikHeroes"},
    }
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    report = importer.run()

    assert report.categories_staged == 1
    staged = import_repo.list_staging_products()[0]
    categories = import_repo.list_categories(staged.id)
    assert categories[0].external_category_id == "CAT-7"
    assert categories[0].external_category_name == "MusikHeroes"


def test_import_part_without_category_stages_none(import_repo: ProductHubImportRepository) -> None:
    raw = {"id": "509", "partNumber": "XW-509", "name": "Ohne Kategorie"}
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    report = importer.run()

    assert report.categories_staged == 0
    staged = import_repo.list_staging_products()[0]
    assert import_repo.list_categories(staged.id) == []


def test_import_part_without_sku_stages_blank_sku_without_inventing_one(
    import_repo: ProductHubImportRepository,
) -> None:
    """Build-plan PR04 rule: a missing SKU stays blank in staging; nothing here may
    invent a placeholder canonical SKU — that decision belongs to matching (PR05/06),
    not the importer. (The legacy ``ProductCatalogService.upsert_from_sevdesk`` does
    synthesize ``SEVDESK-<id>`` — that behavior stays there, untouched, and is not
    reused here.)
    """
    raw = {"id": "503", "name": "Ohne SKU", "stock": "3"}
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    report = importer.run()

    assert report.parts_staged == 1
    staged = import_repo.list_staging_products()[0]
    assert staged.sku is None
    assert staged.source_external_id == "503"


def test_import_parses_stock_from_alternate_field_name(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {"id": "504", "partNumber": "XW-504", "name": "Test", "quantity": "8"}
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    importer.run()

    staged = import_repo.list_staging_products()[0]
    inventory = import_repo.list_inventory(staged.id)
    assert inventory[0].quantity == 8


def test_internal_comment_kept_only_in_normalized_fields(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {
        "id": "505",
        "partNumber": "XW-505",
        "name": "Kommentiert",
        "internalComment": "Nur intern - Einkaufspreis 3.20",
    }
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    importer.run()

    staged = import_repo.list_staging_products()[0]
    assert staged.normalized_fields["internal_comment"] == "Nur intern - Einkaufspreis 3.20"
    assert "description" not in staged.normalized_fields


class _ExplodingStr:
    """Poisons ``json.dumps(..., default=str)`` deterministically for isolation testing."""

    def __str__(self) -> str:
        raise RuntimeError("boom")


def test_import_one_failing_part_does_not_abort_batch(
    import_repo: ProductHubImportRepository,
) -> None:
    good = {"id": "506", "partNumber": "XW-506", "name": "Gut"}
    bad = {"id": "507", "partNumber": "XW-507", "name": "Fehlerhaft", "poison": _ExplodingStr()}
    importer = SevdeskPartImporter(
        parts_client=_FakePartsClient([good, bad]), import_repo=import_repo
    )

    report = importer.run()

    assert report.parts_seen == 2
    assert report.parts_staged == 1
    assert len(report.errors) == 1
    assert "507" in report.errors[0]

    batch = import_repo.get_batch(report.batch_id)
    assert batch is not None
    assert batch.status == "failed"


def test_import_two_runs_each_create_independent_batches(
    import_repo: ProductHubImportRepository,
) -> None:
    raw = {"id": "508", "partNumber": "XW-508", "name": "Wiederholt"}
    importer = SevdeskPartImporter(parts_client=_FakePartsClient([raw]), import_repo=import_repo)

    first_report = importer.run()
    second_report = importer.run()

    assert first_report.batch_id != second_report.batch_id
    assert len(import_repo.list_staging_products()) == 2
