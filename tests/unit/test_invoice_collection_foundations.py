"""Contract tests for the invoice-collection vertical foundation slice."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import logging
import sqlite3

import fitz
import pytest

from xw_office.services.invoice_collection.connectors.manual_import import ManualImportConnector
from xw_office.services.invoice_collection.auth import secrets as secrets_module
from xw_office.services.invoice_collection.auth.secrets import KeyringSecretStore
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import (
    AuthStatus,
    ConfigurationStatus,
    DateRange,
    DocumentCandidate,
    DocumentOutcome,
    DocumentType,
    DownloadedArtifact,
    ProviderConnection,
    RouteSettings,
    RunStatus,
    TenantId,
)
from xw_office.services.invoice_collection.errors import (
    DocumentValidationError,
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.factories import ConnectorFactoryRegistry
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.invoice_date import extract_invoice_date_from_text
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
from xw_office.services.invoice_collection.pdf_validation import inspect_pdf
from xw_office.services.invoice_collection.registry import (
    ProviderCatalog,
    ProviderManifest,
    RouteManifest,
)
from xw_office.services.invoice_collection.security import redact_sensitive_text
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink
from xw_office.services.invoice_collection.orchestrator import CollectionOrchestrator
from xw_office.services.invoice_collection.service import InvoiceCollectionService
from xw_office.core.logging_setup import _SecretRedactionFilter


def _pdf(path: Path, text: str = "invoice") -> Path:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(path)
    return path


def _candidate(
    connection: ProviderConnection,
    *,
    source_id: str,
    external_id: str | None = None,
) -> DocumentCandidate:
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
    assert len(catalog.providers) == 18
    assert sum(len(provider.routes) for provider in catalog.providers) == 26
    assert all(
        route.maturity == "planned"
        for provider in catalog.providers
        for route in provider.routes
    )


def test_registry_rejects_secret_values_and_unknown_tenant(tmp_path: Path) -> None:
    secret_catalog = tmp_path / "secret.yaml"
    secret_catalog.write_text(
        """
schema_version: 2
supported_tenants: [xw]
allowed_document_types: [unknown]
allowed_route_methods: [manual_import]
allowed_provider_categories: [expense]
providers:
  - id: fixture
    label: Fixture
    category: expense
    supported_tenants: [xw]
    document_types: [unknown]
    api_token: should-not-be-here
    routes: []
""",
        encoding="utf-8",
    )
    with pytest.raises(InvoiceCollectionError) as secret_error:
        ProviderCatalog.from_yaml(secret_catalog)
    assert secret_error.value.code == InvoiceErrorCode.CONFIGURATION_ERROR

    tenant_catalog = tmp_path / "tenant.yaml"
    tenant_catalog.write_text(
        secret_catalog.read_text(encoding="utf-8").replace(
            "    api_token: should-not-be-here\n", "    supported_tenants: [other]\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvoiceCollectionError) as tenant_error:
        ProviderCatalog.from_yaml(tenant_catalog)
    assert tenant_error.value.code == InvoiceErrorCode.CONFIGURATION_ERROR


def test_domain_exposes_independent_connection_auth_run_document_and_sync_states() -> None:
    assert ConfigurationStatus.READY.value == "READY"
    assert AuthStatus.NEEDS_LOGIN.value == "NEEDS_LOGIN"
    assert RunStatus.WAITING_FOR_USER.value == "WAITING_FOR_USER"


def test_redaction_never_returns_secret_value() -> None:
    message = redact_sensitive_text("Authorization: Bearer abc123 api_token=secret-value")
    assert "abc123" not in message
    assert "secret-value" not in message
    assert "redacted" in message


def test_global_log_filter_redacts_bearer_token() -> None:
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "Authorization: Bearer %s", ("abc123",), None
    )
    _SecretRedactionFilter().filter(record)
    assert "abc123" not in record.getMessage()
    assert "redacted" in record.getMessage()


def test_keyring_secret_store_uses_secret_ref_without_plaintext_file() -> None:
    class FakeKeyring:
        values: dict[tuple[str, str], str] = {}

        @classmethod
        def get_password(cls, service: str, key: str) -> str | None:
            return cls.values.get((service, key))

        @classmethod
        def set_password(cls, service: str, key: str, value: str) -> None:
            cls.values[(service, key)] = value

    store = KeyringSecretStore(keyring_module=FakeKeyring)
    store.set("provider/connection/token", "secret-value")
    assert store.get("provider/connection/token") == "secret-value"
    assert FakeKeyring.values == {
        ("xw-office/invoice-collection", "provider/connection/token"): "secret-value"
    }


def test_keyring_secret_store_explains_missing_optional_dependency(monkeypatch) -> None:
    def missing_keyring(module_name: str) -> object:
        assert module_name == "keyring"
        raise ImportError("keyring package is not installed")

    monkeypatch.setattr(secrets_module, "import_module", missing_keyring)

    with pytest.raises(InvoiceCollectionError) as error:
        KeyringSecretStore()

    assert error.value.code == InvoiceErrorCode.CONFIGURATION_ERROR
    assert "keyring" in str(error.value).casefold()


def test_pdf_inspection_rejects_html_with_pdf_extension(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_text("<html>not a pdf</html>", encoding="utf-8")
    with pytest.raises(DocumentValidationError):
        inspect_pdf(path)


def test_pipeline_quarantines_invalid_artifact(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    source.write_text("not a PDF", encoding="utf-8")
    pipeline = DocumentPipeline(
        sink=OneDriveLocalSink(tmp_path / "onedrive"),
        quarantine_root=tmp_path / "quarantine",
    )
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
    )
    with pytest.raises(DocumentValidationError):
        pipeline.process(
            DownloadedArtifact(_candidate(connection, source_id="broken"), source)
        )
    assert not source.exists()
    assert list((tmp_path / "quarantine").glob("broken.pdf"))


def test_invoice_date_extraction_requires_one_explicitly_labeled_date() -> None:
    assert extract_invoice_date_from_text("Rechnungsdatum: 31.10.2026") == date(2026, 10, 31)
    assert extract_invoice_date_from_text("Invoice date: 2026-11-02") == date(2026, 11, 2)
    assert (
        extract_invoice_date_from_text(
            "Invoice date: 2026-11-02\nRechnungsdatum: 2026-11-03"
        )
        is None
    )
    assert extract_invoice_date_from_text("Payment due: 2026-11-02") is None


def test_pipeline_sends_unknown_or_out_of_period_dates_to_review_folder(tmp_path: Path) -> None:
    destination = tmp_path / "onedrive"
    destination.mkdir()
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="billing"
    )
    candidate_without_date = DocumentCandidate(
        connection=connection,
        route_key="mail_pdf",
        source_id="message:attachment",
        external_id="message:attachment",
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
    )
    unknown_source = _pdf(tmp_path / "unknown.pdf", "Invoice amount 25 EUR")
    pipeline = DocumentPipeline(
        sink=OneDriveLocalSink(destination),
        quarantine_root=tmp_path / "quarantine",
        period=DateRange(date(2026, 11, 1), date(2026, 11, 30)),
    )

    unknown_result = pipeline.process(
        DownloadedArtifact(candidate_without_date, unknown_source)
    )
    assert unknown_result.receipt.review_reason == "Rechnungsdatum ungeklärt"
    assert "_needs_review" in unknown_result.receipt.target_path.parts
    assert "11" not in unknown_result.receipt.target_path.parts

    october_candidate = _candidate(connection, source_id="late-october")
    october_candidate = DocumentCandidate(
        connection=october_candidate.connection,
        route_key=october_candidate.route_key,
        source_id=october_candidate.source_id,
        external_id=october_candidate.external_id,
        document_type=october_candidate.document_type,
        original_filename=october_candidate.original_filename,
        document_date=date(2026, 10, 31),
    )
    october_source = _pdf(tmp_path / "october.pdf", "Rechnungsdatum: 31.10.2026")
    with pytest.raises(InvoiceCollectionError) as error:
        pipeline.process(DownloadedArtifact(october_candidate, october_source))
    assert error.value.code is InvoiceErrorCode.OUT_OF_PERIOD
    assert not list(destination.rglob("*october*"))

    october_target = tmp_path / "october-onedrive"
    october_target.mkdir()
    october_pipeline = DocumentPipeline(
        sink=OneDriveLocalSink(october_target),
        quarantine_root=tmp_path / "quarantine",
        period=DateRange(date(2026, 10, 1), date(2026, 10, 31)),
    )
    october_archive_result = october_pipeline.process(
        DownloadedArtifact(
            DocumentCandidate(
                connection=connection,
                route_key="mail_pdf",
                source_id="late-october-extracted",
                external_id="late-october-extracted",
                document_type=DocumentType.EXPENSE_INVOICE,
                original_filename="october.pdf",
            ),
            october_source,
        )
    )
    assert october_archive_result.receipt.review_reason is None
    assert october_archive_result.document.candidate.document_date == date(2026, 10, 31)
    relative_target = october_archive_result.receipt.target_path.relative_to(october_target)
    assert relative_target.parts[1:3] == ("2026", "10")


def test_invoice_journal_migrates_v1_and_rejects_newer_schema(tmp_path: Path) -> None:
    old_path = tmp_path / "old-journal.sqlite3"
    with sqlite3.connect(old_path) as connection:
        connection.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')"
        )
    migrated = InvoiceJournal(old_path)
    with sqlite3.connect(old_path) as connection:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert version == "3"
    assert "collection_runs" in tables
    assert "collection_checkpoints" in tables
    assert "document_provenance" in tables
    assert migrated.path == old_path

    newer_path = tmp_path / "newer-journal.sqlite3"
    with sqlite3.connect(newer_path) as connection:
        connection.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '4')"
        )
    with pytest.raises(RuntimeError, match="newer than supported"):
        InvoiceJournal(newer_path)


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


def test_same_tenant_cross_route_duplicate_publishes_once_and_merges_safe_provenance(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "invoice.pdf", "Invoice date: 2026-11-05")
    conflicting_source = _pdf(tmp_path / "changed.pdf", "Invoice date: 2026-11-06")
    destination = tmp_path / "onedrive"
    destination.mkdir()
    journal_path = tmp_path / "journal.sqlite3"
    journal = InvoiceJournal(journal_path)
    pipeline = DocumentPipeline(
        sink=OneDriveLocalSink(destination),
        journal=journal,
    )
    mail_connection = ProviderConnection.create(
        provider_id="browserstack",
        tenant_id=TenantId.XW,
        account_alias="billing",
    )
    api_connection = ProviderConnection.create(
        provider_id="mollie_fees",
        tenant_id=TenantId.XW,
        account_alias="fees",
    )
    mail_candidate = DocumentCandidate(
        connection=mail_connection,
        route_key="mail_pdf",
        source_id="opaque-mail-source",
        external_id=None,
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 5),
    )
    api_candidate = DocumentCandidate(
        connection=api_connection,
        route_key="invoices_api",
        source_id="opaque-api-source",
        external_id="private-api-resource-id",
        document_type=DocumentType.FEE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 5),
    )

    first = pipeline.process(DownloadedArtifact(mail_candidate, source))
    duplicate = pipeline.process(DownloadedArtifact(api_candidate, source))

    assert first.receipt.outcome is DocumentOutcome.NEW
    assert duplicate.receipt.outcome is DocumentOutcome.ALREADY_PRESENT
    assert first.receipt.target_path == duplicate.receipt.target_path
    assert len(list(destination.rglob("*.pdf"))) == 1
    provenance = journal.list_provenance(
        tenant_id=TenantId.XW.value,
        sink_id=OneDriveLocalSink.sink_id,
        sha256=first.document.sha256,
    )
    assert {item.route_key for item in provenance} == {"mail_pdf", "invoices_api"}
    assert all("private-api-resource-id" not in item.source_id_hash for item in provenance)
    assert b"private-api-resource-id" not in journal_path.read_bytes()

    changed_api_candidate = DocumentCandidate(
        connection=api_connection,
        route_key="invoices_api",
        source_id="changed-api-source",
        external_id="private-api-resource-id",
        document_type=DocumentType.FEE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 6),
    )
    with pytest.raises(InvoiceCollectionError) as error:
        pipeline.process(DownloadedArtifact(changed_api_candidate, conflicting_source))
    assert error.value.code is InvoiceErrorCode.CONTENT_CONFLICT


def test_orchestrator_returns_safe_provenance_route_labels_for_duplicate(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "invoice.pdf", "Invoice date: 2026-11-05")
    destination = tmp_path / "onedrive"
    destination.mkdir()
    journal = InvoiceJournal(tmp_path / "journal.sqlite3")
    pipeline = DocumentPipeline(sink=OneDriveLocalSink(destination), journal=journal)
    mail_connection = ProviderConnection.create(
        provider_id="browserstack", tenant_id=TenantId.XW, account_alias="billing"
    )
    api_connection = ProviderConnection.create(
        provider_id="mollie_fees", tenant_id=TenantId.XW, account_alias="fees"
    )

    class FixtureConnector:
        route_key = "fixture"

        def __init__(self, candidate: DocumentCandidate) -> None:
            self.connection = candidate.connection
            self.candidate = candidate

        def discover(self) -> list[DocumentCandidate]:
            return [self.candidate]

        def download(self, candidate, workspace, cancel=None):
            return DownloadedArtifact(candidate=candidate, path=source)

    mail_candidate = DocumentCandidate(
        connection=mail_connection,
        route_key="mail_pdf",
        source_id="opaque-mail-id",
        external_id=None,
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 5),
    )
    api_candidate = DocumentCandidate(
        connection=api_connection,
        route_key="invoices_api",
        source_id="opaque-api-id",
        external_id="private-api-resource-id",
        document_type=DocumentType.FEE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 5),
    )
    orchestrator = CollectionOrchestrator(pipeline, journal=journal)

    orchestrator.collect([FixtureConnector(mail_candidate)])
    result = orchestrator.collect([FixtureConnector(api_candidate)])

    assert result.items[0].provenance == (
        "browserstack/mail_pdf",
        "mollie_fees/invoices_api",
    )
    assert "private-api-resource-id" not in result.items[0].provenance


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
        DownloadedArtifact(
            _candidate(connection, source_id="one", external_id="invoice-1"), first_source
        )
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
    assert any(item.error for item in summary.items)
    assert any(item.outcome is not None and item.outcome.value == "NEW" for item in summary.items)


def test_orchestrator_isolates_discovery_failure_and_uses_connection_lock(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "after-discovery-error.pdf")
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
    )

    class BrokenDiscovery:
        route_key = "broken"

        def __init__(self) -> None:
            self.connection = connection

        def discover(self) -> list[DocumentCandidate]:
            raise RuntimeError("authorization token must not be shown")

        def download(self, candidate: DocumentCandidate, workspace: Path, cancel: object = None):
            raise AssertionError("download should not be called")

    good = ManualImportConnector(connection=connection, files=[source])
    sink_root = tmp_path / "onedrive"
    sink_root.mkdir()
    summary = CollectionOrchestrator(
        DocumentPipeline(sink=OneDriveLocalSink(sink_root)), workspace_root=tmp_path
    ).collect([BrokenDiscovery(), good])  # type: ignore[list-item]
    assert summary.new_count == 1
    failed = next(item for item in summary.items if item.route_key == "broken")
    assert failed.error == "INTERNAL_ERROR: RuntimeError"
    assert "token" not in failed.error.casefold()


def test_orchestrator_limits_parallel_connector_workers(tmp_path: Path) -> None:
    source_one = _pdf(tmp_path / "one.pdf", "one")
    source_two = _pdf(tmp_path / "two.pdf", "two")
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
    )
    sink_root = tmp_path / "onedrive"
    sink_root.mkdir()
    pipeline = DocumentPipeline(sink=OneDriveLocalSink(sink_root))
    connectors = [
        ManualImportConnector(connection=connection, files=[source_one]),
        ManualImportConnector(connection=connection, files=[source_two]),
    ]
    summary = CollectionOrchestrator(
        pipeline, workspace_root=tmp_path, max_workers=2
    ).collect(connectors)
    assert summary.new_count == 2


def test_orchestrator_honors_cooperative_cancellation_before_start(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "cancelled.pdf")
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
    )
    connector = ManualImportConnector(connection=connection, files=[source])
    sink_root = tmp_path / "onedrive"
    sink_root.mkdir()
    pipeline = DocumentPipeline(sink=OneDriveLocalSink(sink_root))

    class Cancelled:
        cancelled = True

    summary = CollectionOrchestrator(pipeline).collect([connector], cancel=Cancelled())
    assert summary.cancelled is True
    assert summary.items == ()


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


def test_collection_isolates_invalid_saved_connection_and_keeps_valid_accounts_running(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "valid-account.pdf")
    repository_path = tmp_path / "connections.sqlite3"
    repository = ConnectionRepository(repository_path)
    valid = ProviderConnection.create(
        provider_id="fixture",
        tenant_id=TenantId.XW,
        account_alias="billing",
        route_settings=(
            RouteSettings(route_key="manual_import", options={"connector": "fixture"}),
        ),
    )
    invalid = ProviderConnection.create(
        provider_id="legacy",
        tenant_id=TenantId.XW,
        account_alias="invalid",
    )
    repository.save(valid)
    with sqlite3.connect(repository_path) as connection:
        connection.execute(
            "INSERT INTO provider_connections VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(invalid.connection_id),
                "legacy",
                "invalid-tenant",
                "invalid",
                1,
                "[]",
            ),
        )
    factories = ConnectorFactoryRegistry()
    factories.register(
        "fixture",
        lambda saved, _settings, _period: ManualImportConnector(
            connection=saved, files=[source]
        ),
    )
    target = tmp_path / "onedrive"
    target.mkdir()

    run = InvoiceCollectionService(
        connections=repository,
        factories=factories,
        target_root=target,
        journal=InvoiceJournal(tmp_path / "journal.sqlite3"),
    ).collect_active()

    assert run.status is RunStatus.PARTIAL
    assert run.summary.new_count == 1
    assert len(run.issues) == 1
    assert run.issues[0].route_key == "connection_configuration"
    assert run.issues[0].message.startswith("CONFIGURATION_ERROR:")
    assert run.issues[0].provider_id is None
    assert run.issues[0].tenant_id is None
    assert run.issues[0].account_alias is None


def test_connector_factory_registry_never_loads_yaml_import_paths() -> None:
    registry = ConnectorFactoryRegistry()
    registry.register("fixture", lambda connection, settings: object())  # type: ignore[arg-type]
    assert registry.keys() == ("fixture",)
    with pytest.raises(ValueError):
        registry.register(
            "package.module", lambda connection, settings: object()
        )  # type: ignore[arg-type]
    with pytest.raises(InvoiceCollectionError) as error:
        registry.create("unknown", ProviderConnection.create(
            provider_id="fixture", tenant_id=TenantId.XW, account_alias="a"
        ), object())  # type: ignore[arg-type]
    assert error.value.code == InvoiceErrorCode.CONFIGURATION_ERROR


def test_collection_service_wires_saved_routes_to_factory_and_orchestrator(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "saved-route.pdf")
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    connection = ProviderConnection.create(
        provider_id="fixture",
        tenant_id=TenantId.XW,
        account_alias="billing",
        route_settings=(
            RouteSettings(route_key="manual_import", options={"connector": "fixture"}),
        ),
    )
    repository.save(connection)
    factories = ConnectorFactoryRegistry()
    selected_period = DateRange(date(2026, 11, 1), date(2026, 11, 30))
    received_periods: list[DateRange | None] = []

    def make_connector(saved: ProviderConnection, settings: RouteSettings, period: DateRange | None):
        received_periods.append(period)
        return ManualImportConnector(connection=saved, files=[source])

    factories.register(
        "fixture",
        make_connector,
    )
    target = tmp_path / "onedrive"
    target.mkdir()
    journal = InvoiceJournal(tmp_path / "journal.sqlite3")
    service = InvoiceCollectionService(
        connections=repository,
        factories=factories,
        target_root=target,
        journal=journal,
    )
    run = service.collect_active(period=selected_period)
    assert run.issues == ()
    assert run.summary.new_count == 1
    assert run.status is RunStatus.SUCCEEDED
    assert run.run_id is not None
    assert journal.run_status(run.run_id) == RunStatus.SUCCEEDED.value
    assert journal.checkpoint_count(run_id=run.run_id, route_key="manual_import") == 1
    assert received_periods == [selected_period]
    item = run.summary.items[0]
    assert item.provider_id == "fixture"
    assert item.tenant_id == "xw"
    assert item.account_alias == "billing"
    assert item.display_name == "saved-route.pdf"

    repeated = service.collect_active(period=selected_period)
    assert repeated.status is RunStatus.SUCCEEDED
    assert repeated.resumed is False
    assert repeated.run_id != run.run_id
    assert repeated.summary.new_count == 0
    assert repeated.summary.existing_count == 1


def test_service_resumes_cancelled_run_with_same_context_without_persisting_target_or_mailbox(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "resume-route.pdf")
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    connection = ProviderConnection.create(
        provider_id="fixture",
        tenant_id=TenantId.XW,
        account_alias="billing",
        route_settings=(
            RouteSettings(
                route_key="manual_import",
                options={
                    "connector": "fixture",
                    "mailbox": "billing@example.test",
                    "sender_domains": "vendor.example.test",
                },
            ),
        ),
    )
    repository.save(connection)
    factories = ConnectorFactoryRegistry()
    factories.register(
        "fixture",
        lambda saved, _settings, _period: ManualImportConnector(
            connection=saved, files=[source]
        ),
    )
    target = tmp_path / "resume-onedrive"
    target.mkdir()
    journal_path = tmp_path / "resume-journal.sqlite3"
    journal = InvoiceJournal(journal_path)
    service = InvoiceCollectionService(
        connections=repository,
        factories=factories,
        target_root=target,
        journal=journal,
    )

    class Cancelled:
        cancelled = True

    period = DateRange(date(2026, 11, 1), date(2026, 11, 30))
    interrupted = service.collect_active(period=period, cancel=Cancelled())
    assert interrupted.status is RunStatus.CANCELLED
    assert interrupted.run_id is not None
    assert journal.run_status(interrupted.run_id) == RunStatus.CANCELLED.value

    resumed = service.collect_active(period=period)

    assert resumed.run_id == interrupted.run_id
    assert resumed.resumed is True
    assert resumed.status is RunStatus.SUCCEEDED
    assert journal.run_status(resumed.run_id or "") == RunStatus.SUCCEEDED.value
    assert journal.checkpoint_count(
        run_id=resumed.run_id or "", route_key="manual_import"
    ) == 1
    journal_bytes = journal_path.read_bytes()
    assert b"billing@example.test" not in journal_bytes
    assert str(target).encode("utf-8") not in journal_bytes


def test_orchestrator_reports_empty_route_without_source_identifiers(tmp_path: Path) -> None:
    connection = ProviderConnection.create(
        provider_id="fixture", tenant_id=TenantId.XW, account_alias="billing"
    )

    class EmptyConnector:
        route_key = "fixture_mail"

        def __init__(self) -> None:
            self.connection = connection

        def discover(self) -> list[object]:
            return []

        def download(self, *_args: object) -> object:
            raise AssertionError("empty route must not download")

    sink_root = tmp_path / "onedrive"
    sink_root.mkdir()
    summary = CollectionOrchestrator(
        DocumentPipeline(sink=OneDriveLocalSink(sink_root))
    ).collect([EmptyConnector()])

    assert len(summary.items) == 1
    item = summary.items[0]
    assert item.route_key == "fixture_mail"
    assert item.provider_id == "fixture"
    assert item.tenant_id == "xw"
    assert item.account_alias == "billing"
    assert item.outcome is None
    assert item.error is None


def test_collection_service_blocks_saved_route_that_catalog_marks_planned(tmp_path: Path) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    connection = ProviderConnection.create(
        provider_id="fixture",
        tenant_id=TenantId.XW,
        account_alias="billing",
        route_settings=(
            RouteSettings(route_key="mail_pdf", options={"connector": "fixture"}),
        ),
    )
    repository.save(connection)
    factories = ConnectorFactoryRegistry()
    factories.register("fixture", lambda *_args: pytest.fail("planned route factory invoked"))
    catalog = ProviderCatalog(
        schema_version=2,
        providers=(
            ProviderManifest(
                provider_id="fixture",
                label="Fixture",
                category="expense",
                supported_tenants=frozenset({"xw"}),
                document_types=frozenset({"expense_invoice"}),
                routes=(
                    RouteManifest(
                        route_key="mail_pdf",
                        method="mail",
                        connector="graph_mail_attachment",
                        priority=10,
                        maturity="planned",
                    ),
                ),
            ),
        ),
    )
    target = tmp_path / "onedrive"
    target.mkdir()
    run = InvoiceCollectionService(
        connections=repository,
        factories=factories,
        target_root=target,
        journal=InvoiceJournal(tmp_path / "journal.sqlite3"),
        catalog=catalog,
    ).collect_active()
    assert run.summary.items == ()
    assert len(run.issues) == 1
    assert run.issues[0].message.startswith("UNSUPPORTED_ACCOUNT:")
