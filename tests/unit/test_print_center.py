"""Isolation, readonly catalogues, stale writes and spooler-confirmed printing."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from xw_office.core.config import PrintingSection
from xw_office.models import Base
from xw_office.models.product_hub import Product, ProductAsset, ProductVariant, PrintRule
from xw_office.models.settings_kv import SettingKV
from xw_office.print_center.models import (
    ArticleInput, OwnArticle, PrintArticle, PrintCenterBase, PrintStep,
)
from xw_office.print_center.official import OfficialCatalogue
from xw_office.print_center.repository import OwnArticleRepository, provision_storage
from xw_office.print_center.service import PrintCenterService
from xw_office.services.printing.print_jobs import PdfPrintJob, PrintJobResult
from xw_office.services.printing.planned_pdf_printer import PrintPlanPartialFailure
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.products.catalog import ProductCatalogService


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        execution_options={"schema_translate_map": {"print_center": None}},
    )
    Base.metadata.create_all(engine)
    provision_storage(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(SettingKV(key="inventory.products", value_json="[]"))
    yield factory
    engine.dispose()


@pytest.fixture
def printing() -> PrintingSection:
    return PrintingSection(print_profiles=[
        {"id": "score", "label": "Noten", "printer_name": "Test printer", "backend": "pdf_xchange"},
        {"id": "raster", "printer_name": "Test printer", "backend": "qt_raster"},
    ])


@pytest.fixture
def pdf(tmp_path: Path) -> str:
    path = tmp_path / "test.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        doc.save(path)
    return str(path)


def article_input(pdf: str) -> ArticleInput:
    return ArticleInput(name="Private Noten", pdf_path=pdf, print_plan=(
        PrintStep(range="1", profile_id="score"),
        PrintStep(range="2", profile_id="score"),
    ))


def queue_mock() -> MagicMock:
    queue = MagicMock(spec=PrintQueueService)
    queue.enqueue_and_wait.side_effect = lambda job: PrintJobResult(
        job_id=job.id, success=True, description=job.description, printer_name=job.printer_name,
    )
    return queue


def service(
    sessions: sessionmaker[Session], printing: PrintingSection, queue: MagicMock,
) -> PrintCenterService:
    return PrintCenterService(
        OfficialCatalogue(sessions), OwnArticleRepository(sessions), lambda: printing, queue,
    )


def test_own_crud_has_no_sku_and_never_enters_office(sessions: sessionmaker[Session], pdf: str) -> None:
    repository = OwnArticleRepository(sessions)
    saved = repository.save(article_input(pdf))
    assert saved.sku == ""
    assert saved.source == "own"
    assert saved.row_version == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Product)) == 0
        assert session.scalar(select(func.count()).select_from(ProductVariant)) == 0
        assert session.get(SettingKV, "inventory.products").value_json == "[]"
    assert OfficialCatalogue(sessions).list_articles() == []
    assert "print_center.article" not in Base.metadata.tables
    assert "sku" not in PrintCenterBase.metadata.tables["print_center.article"].columns
    updated = repository.save(
        article_input(pdf).model_copy(update={"name": "Geaendert"}),
        article_id=saved.id, version=saved.row_version,
    )
    assert updated.row_version == 2
    assert repository.get(saved.id).name == "Geaendert"
    with pytest.raises(ValueError, match="anderen PC"):
        repository.save(article_input(pdf), article_id=saved.id, version=1)
    with pytest.raises(ValueError, match="inzwischen"):
        repository.delete(saved.id, version=1)
    repository.delete(saved.id, version=2)
    assert repository.list_articles() == []
    assert Path(pdf).is_file()
    with pytest.raises(ValidationError):
        ArticleInput.model_validate({**article_input(pdf).model_dump(), "sku": "UNWANTED"})


def test_storage_is_additive_and_idempotent(sessions: sessionmaker[Session]) -> None:
    engine = sessions.kw["bind"]
    provision_storage(engine)
    assert inspect(engine).has_table("article")
    assert not OwnArticle.__table__.foreign_keys


def seed_official(sessions: sessionmaker[Session], pdf: str) -> None:
    with sessions.begin() as session:
        session.get(SettingKV, "inventory.products").value_json = json.dumps([{
            "sku": "SCORE", "name": "Offiziell", "print_file_path": pdf,
            "print_profile_id": "score",
            "title_print_configs": {"Spezial": {
                "path": pdf, "profile_id": "score", "print_plan": [],
            }},
        }, {"sku": "DIGITAL", "is_digital": True}])
        product = Product(sku="SCORE", name="Hub Titel", slug="hub-titel")
        session.add(product)
        session.flush()
        variant = ProductVariant(product_id=product.id, sku="SCORE", is_default=True)
        session.add(variant)
        session.flush()
        session.add_all([
            ProductAsset(product_id=product.id, variant_id=variant.id, role="PRINT_PDF",
                         storage_kind="NETWORK_PATH", uri=pdf),
            PrintRule(variant_id=variant.id, print_profile_id="score"),
        ])


def test_official_legacy_titles_and_hub_precedence(
    sessions: sessionmaker[Session], pdf: str,
) -> None:
    seed_official(sessions, pdf)
    before: str
    with sessions() as session:
        before = session.get(SettingKV, "inventory.products").value_json
    legacy = OfficialCatalogue(sessions).list_articles()
    assert [(a.name, a.sku) for a in legacy] == [("Offiziell", "SCORE"), ("Spezial", "SCORE")]
    hub = OfficialCatalogue(sessions, prefer_hub=True).list_articles()
    assert {a.name for a in hub} == {"Hub Titel", "Spezial"}
    with sessions() as session:
        assert session.get(SettingKV, "inventory.products").value_json == before


def test_invalid_catalogue_fails_explicitly(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.get(SettingKV, "inventory.products").value_json = "not json"
    with pytest.raises(ValidationError):
        OfficialCatalogue(sessions).list_articles()


def test_generic_unreleased_sku_never_prints_another_titles_default(
    sessions: sessionmaker[Session], pdf: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = MagicMock(return_value={})
    monkeypatch.setattr(ProductCatalogService, "_resolve_unreleased_pdf_config", resolver)
    with sessions.begin() as session:
        session.get(SettingKV, "inventory.products").value_json = json.dumps([{
            "sku": "XW-010", "name": "Unreleased", "print_file_path": pdf,
            "print_profile_id": "score",
        }])
        product = Product(sku="XW-010", name="Unreleased", slug="unreleased")
        session.add(product)
        session.flush()
        variant = ProductVariant(product_id=product.id, sku="XW-010", is_default=True)
        session.add(variant)
        session.flush()
        session.add_all([
            ProductAsset(product_id=product.id, variant_id=variant.id, role="PRINT_PDF",
                         storage_kind="NETWORK_PATH", uri=pdf),
            PrintRule(variant_id=variant.id, print_profile_id="score"),
        ])
    for prefer_hub in (False, True):
        articles = OfficialCatalogue(sessions, prefer_hub=prefer_hub).list_articles()
        assert len(articles) == 1
        assert articles[0].pdf_path == ""
    assert all(call.args[0] == "Unreleased" for call in resolver.call_args_list)


def test_print_own_dispatches_complete_sets_and_waits_for_confirmation(
    sessions: sessionmaker[Session], printing: PrintingSection, pdf: str,
) -> None:
    queue = queue_mock()
    center = service(sessions, printing, queue)
    saved = center.save_own(article_input(pdf))
    receipt = center.print_article(saved, 2)
    assert receipt.copies == 2
    assert len(receipt.job_ids) == 4
    jobs = [call.args[0] for call in queue.enqueue_and_wait.call_args_list]
    assert [j.pages for j in jobs] == [[0], [1], [0], [1]]
    assert all(j.backend == "pdf_xchange" and j.copies == 1 for j in jobs)
    queue.enqueue.assert_not_called()


def test_official_print_reloads_instead_of_trusting_modified_selection(
    sessions: sessionmaker[Session], printing: PrintingSection, pdf: str,
) -> None:
    seed_official(sessions, pdf)
    queue = queue_mock()
    center = service(sessions, printing, queue)
    selection = center.list_articles()[0]
    tampered = selection.model_copy(update={"pdf_path": "untrusted.pdf", "profile_id": "raster"})
    center.print_article(tampered, 1)
    assert queue.enqueue_and_wait.call_args.args[0].pdf_path == pdf
    assert queue.enqueue_and_wait.call_args.args[0].backend == "pdf_xchange"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(OwnArticle)) == 0


def test_print_failure_reports_partial_copies(
    sessions: sessionmaker[Session], printing: PrintingSection, pdf: str,
) -> None:
    queue = queue_mock()
    center = service(sessions, printing, queue)
    saved = center.save_own(article_input(pdf))
    count = 0

    def result(job: PdfPrintJob) -> PrintJobResult:
        nonlocal count
        count += 1
        return PrintJobResult(
            job_id=job.id, success=count < 3, message="Spooler fehlt",
            description=job.description, printer_name=job.printer_name,
        )

    queue.enqueue_and_wait.side_effect = result
    with pytest.raises(PrintPlanPartialFailure) as failure:
        center.print_article(saved, 2)
    assert failure.value.completed_copies == 1
    assert queue.enqueue_and_wait.call_count == 3


def test_native_only_and_all_ranges_preflight_before_dispatch(
    sessions: sessionmaker[Session], printing: PrintingSection, pdf: str,
) -> None:
    queue = queue_mock()
    center = service(sessions, printing, queue)
    with pytest.raises(ValueError, match="PDF-XChange"):
        center.save_own(article_input(pdf).model_copy(update={
            "print_plan": (PrintStep(profile_id="raster"),),
        }))
    with pytest.raises(RuntimeError, match="ausserhalb"):
        center.save_own(article_input(pdf).model_copy(update={
            "print_plan": (PrintStep(range="3", profile_id="score"),),
        }))
    saved = OwnArticleRepository(sessions).save(article_input(pdf).model_copy(update={
        "print_plan": (
            PrintStep(range="1", profile_id="score"), PrintStep(range="3", profile_id="score"),
        ),
    }))
    with pytest.raises(RuntimeError, match="ausserhalb"):
        center.print_article(saved, 1)
    queue.enqueue_and_wait.assert_not_called()


@pytest.mark.parametrize("copies", [0, 1000])
def test_quantity_bounds(
    sessions: sessionmaker[Session], printing: PrintingSection, copies: int,
) -> None:
    queue = queue_mock()
    center = service(sessions, printing, queue)
    with pytest.raises(ValueError, match="1 und 999"):
        center.print_article(PrintArticle(id="missing", source="own", name="test"), copies)
    queue.enqueue_and_wait.assert_not_called()
