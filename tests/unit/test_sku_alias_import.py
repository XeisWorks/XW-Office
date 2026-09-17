"""Tests for applying the Master Seed V2 SKU-alias table."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.sku_alias_import import import_sku_aliases

_COLUMNS = ["alias_sku", "canonical_sku", "reason", "source_wix", "source_sevdesk", "source_title_wix", "source_title_erp"]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for row in rows:
            base = {col: "" for col in _COLUMNS}
            base.update(row)
            writer.writerow(base)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def product_repo(session_factory: sessionmaker[Session]) -> ProductHubRepository:
    return ProductHubRepository(session_factory)


def test_import_creates_alias_pointing_to_canonical_variant(
    tmp_path: Path, session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product, variant = product_repo.create_product(sku="XW-4043", name="Zadok The Priest")
    csv_path = tmp_path / "aliases.csv"
    _write_csv(csv_path, [{"alias_sku": "XW-443", "canonical_sku": "XW-4043"}])

    report = import_sku_aliases(session_factory, csv_path)

    assert report.total_rows == 1
    assert report.created == 1
    assert report.errors == []
    resolved = product_repo.resolve_sku("XW-443")
    assert resolved is not None
    assert resolved.product.id == product.id
    assert resolved.variant.id == variant.id
    assert resolved.matched_via == "alias"


def test_import_reports_error_for_unresolvable_canonical_sku(
    tmp_path: Path, session_factory: sessionmaker[Session]
) -> None:
    csv_path = tmp_path / "aliases.csv"
    _write_csv(csv_path, [{"alias_sku": "XW-999", "canonical_sku": "XW-DOES-NOT-EXIST"}])

    report = import_sku_aliases(session_factory, csv_path)

    assert report.created == 0
    assert len(report.errors) == 1
    assert "XW-999" in report.errors[0]


def test_import_is_idempotent(
    tmp_path: Path, session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product_repo.create_product(sku="XW-4043", name="Zadok The Priest")
    csv_path = tmp_path / "aliases.csv"
    _write_csv(csv_path, [{"alias_sku": "XW-443", "canonical_sku": "XW-4043"}])

    first = import_sku_aliases(session_factory, csv_path)
    second = import_sku_aliases(session_factory, csv_path)

    assert first.created == 1
    assert second.created == 0
    assert second.already_existed == 1
    assert second.errors == []


def test_alias_never_creates_its_own_product(
    tmp_path: Path, session_factory: sessionmaker[Session], product_repo: ProductHubRepository
) -> None:
    product_repo.create_product(sku="XW-4043", name="Zadok The Priest")
    csv_path = tmp_path / "aliases.csv"
    _write_csv(csv_path, [{"alias_sku": "XW-443", "canonical_sku": "XW-4043"}])

    import_sku_aliases(session_factory, csv_path)

    assert product_repo.get_product_by_sku("XW-443") is not None  # resolves via alias
    assert product_repo.count_products() == 1  # but no *new* product was created
