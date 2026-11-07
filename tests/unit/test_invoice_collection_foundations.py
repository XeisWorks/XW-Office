"""Contract tests for the invoice-collection vertical foundation slice."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import fitz
import pytest

from xw_office.services.invoice_collection.connectors.manual_import import ManualImportConnector
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    DownloadedArtifact,
    ProviderConnection,
    TenantId,
)
from xw_office.services.invoice_collection.errors import (
    DocumentValidationError,
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
from xw_office.services.invoice_collection.pdf_validation import inspect_pdf
from xw_office.services.invoice_collection.registry import ProviderCatalog
from xw_office.services.invoice_collection.security import redact_sensitive_text
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink
from xw_office.services.invoice_collection.orchestrator import CollectionOrchestrator


def _pdf(path: Path, text: str = "invoice") -> Path:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(path)
    return path


def _candidate(connection: ProviderConnection, *, source_id: str, external_id: str | None = None) -> DocumentCandidate:
    return DocumentCandidate(
        connection=connection,
        route_key="manual_import",
        source_id=source_id,
        external_id=external_id,
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 7),
    )


def test_registry_parses_secret_free_catalog() -> None:
    root = Path(__file__).resolve().parents[2]
    catalog = ProviderCatalog.from_yaml(
        root / "markdowns" / "rechnungsautomat_ausgabenpruefung_2026-11" / "PROVIDER_REGISTRY.yaml"
    )
    assert len(catalog.providers) == 15
    assert sum(len(provider.routes) for provider in catalog.providers) == 24
    assert all(route.maturity == "planned" for provider in catalog.providers for route in provider.routes)


def test_redaction_never_returns_secret_value() -> None:
    message = redact_sensitive_text("Authorization: Bearer abc123 api_token=secret-value")
    assert "abc123" not in message
    assert "secret-value" not in message
    assert "redacted" in message


def test_pdf_inspection_rejects_html_with_pdf_extension(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_text("<html>not a pdf</html>", encoding="utf-8")
    with pytest.raises(DocumentValidationError):
        inspect_pdf(path)


def test_manual_import_uses_pipeline_and_is_idempotent(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "source.pdf")
    destination = tmp_path / "onedrive"
    destination.mkdir()
    connection = ProviderConnection.create(
        provider_id="fixture_provider",
        tenant_id=TenantId.XW,
        account_alias="fixture",
    )
    connector = ManualImportConnector(connection=connection, files=[source])
    sink = OneDriveLocalSink(destination)
    pipeline = DocumentPipeline(sink=sink, journal=InvoiceJournal(tmp_path / "journal.sqlite3"))

    first = pipeline.process(connector.download(connector.discover()[0], tmp_path / "workspace"))
    second = pipeline.process(connector.download(connector.discover()[0], tmp_path / "workspace-2"))

    assert first.receipt.outcome.value == "NEW"
    assert first.receipt.sync_status.value == "SYNC_PENDING"
    assert second.receipt.outcome.value == "ALREADY_PRESENT"
    assert first.receipt.target_path == second.receipt.target_path
    assert first.receipt.target_path.read_bytes() == source.read_bytes()


def test_same_content_is_not_deduplicated_across_tenants(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "source.pdf")
    destination = tmp_path / "onedrive"
    destination.mkdir()
    sink = OneDriveLocalSink(destination)
    pipeline = DocumentPipeline(sink=sink)
    xw = ProviderConnection.create(provider_id="fixture", tenant_id=TenantId.XW, account_alias="a")
    wuedara = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.WUEDARA, account_alias="a"
    )
    first = pipeline.process(
        DownloadedArtifact(_candidate(xw, source_id="one"), source)
    )
    second = pipeline.process(
        DownloadedArtifact(_candidate(wuedara, source_id="two"), source)
    )
    assert first.receipt.target_path != second.receipt.target_path
    assert first.receipt.target_path.exists()
    assert second.receipt.target_path.exists()


def test_external_id_with_different_hash_is_a_conflict(tmp_path: Path) -> None:
    first_source = _pdf(tmp_path / "first.pdf", "one")
    second_source = _pdf(tmp_path / "second.pdf", "two")
    destination = tmp_path / "onedrive"
    destination.mkdir()
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
    )
    journal = InvoiceJournal(tmp_path / "journal.sqlite3")
    pipeline = DocumentPipeline(sink=OneDriveLocalSink(destination), journal=journal)
    pipeline.process(
        DownloadedArtifact(_candidate(connection, source_id="one", external_id="invoice-1"), first_source)
    )
    with pytest.raises(InvoiceCollectionError) as error:
        pipeline.process(
            DownloadedArtifact(
                _candidate(connection, source_id="two", external_id="invoice-1"), second_source
            )
        )
    assert error.value.code == InvoiceErrorCode.CONTENT_CONFLICT


def test_orchestrator_continues_after_one_connector_failure(tmp_path: Path) -> None:
    valid = _pdf(tmp_path / "valid.pdf")
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
    )
    good = ManualImportConnector(connection=connection, files=[valid])
    bad = ManualImportConnector(connection=connection, files=[tmp_path / "missing.pdf"])
    pipeline = DocumentPipeline(sink=OneDriveLocalSink(tmp_path / "onedrive"))
    (tmp_path / "onedrive").mkdir()
    summary = CollectionOrchestrator(pipeline, workspace_root=tmp_path).collect([bad, good])
    assert len(summary.items) == 2
    assert summary.items[0].error
    assert summary.items[1].outcome.value == "NEW"


def test_connection_repository_round_trips_metadata_without_secret_values(tmp_path: Path) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    value = ProviderConnection.create(
        provider_id="fixture",
        tenant_id=TenantId.WUEDARA,
        account_alias="billing",
    )
    repository.save(value)
    loaded = repository.list_enabled()
    assert loaded == [value]
