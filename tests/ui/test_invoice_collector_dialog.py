from __future__ import annotations

from pathlib import Path
from threading import Event
from dataclasses import replace
from datetime import date

import pytest
import fitz

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QFileDialog

from xw_office.core.app_paths import default_invoice_target_dir
from xw_office.ui.modules.expense_review import invoice_collector_dialog as dialog_module
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import (
    DateRange,
    DocumentCandidate,
    DocumentOutcome,
    DocumentType,
    DownloadedArtifact,
    ProviderConnection,
    RouteSettings,
    TenantId,
)
from xw_office.services.invoice_collection.errors import InvoiceCollectionError, InvoiceErrorCode
from xw_office.services.invoice_collection.orchestrator import (
    CollectionItemResult,
    CollectionSummary,
)
from xw_office.services.invoice_collection.service import CollectionRun, ConnectionRouteIssue
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink
from xw_office.ui.modules.expense_review.invoice_collector_dialog import (
    InvoiceCollectorDialog,
    InvoiceRunHistoryDialog,
    _collect_active_safely,
    _looks_like_mailbox,
    _parse_sender_domains,
    _run_collector_operation_safely,
)


def test_default_invoice_target_uses_current_windows_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Bernhard Holl"))
    assert default_invoice_target_dir() == (
        tmp_path / "Bernhard Holl" / "OneDrive - XeisWorks" / "00 Finanzmanagement" / "02 Belege"
    )


def test_collection_worker_boundary_redacts_exception_text_before_logging() -> None:
    class BrokenService:
        def collect_active(self, **_kwargs: object) -> object:
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED,
                "Bearer secret-token from https://provider.example.test/?signed=secret",
            )

    with pytest.raises(InvoiceCollectionError) as raised:
        _collect_active_safely(
            BrokenService(),  # type: ignore[arg-type]
            cancel=object(),  # type: ignore[arg-type]
            period=DateRange(date(2026, 11, 1), date(2026, 11, 30)),
        )

    assert raised.value.code is InvoiceErrorCode.AUTH_REQUIRED
    assert "secret-token" not in str(raised.value)
    assert "signed=secret" not in str(raised.value)
    assert raised.value.__suppress_context__ is True

    def unexpected_failure() -> None:
        raise RuntimeError("Bearer other-secret-token from a signed provider URL")

    with pytest.raises(InvoiceCollectionError) as unexpected:
        _run_collector_operation_safely(unexpected_failure)
    assert unexpected.value.code is InvoiceErrorCode.INTERNAL_ERROR
    assert "other-secret-token" not in str(unexpected.value)
    assert unexpected.value.__suppress_context__ is True


def test_collector_error_status_redacts_untrusted_provider_text(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._fetch_generation = 3
    provider_error = RuntimeError(
        "Bearer secret-token https://provider.example.test/?signed=secret"
    )

    dialog._on_collection_error(3, provider_error)
    assert "secret-token" not in dialog._status.text()
    assert "signed=secret" not in dialog._status.text()

    dialog._on_mail_test_error(provider_error)
    assert "secret-token" not in dialog._status.text()
    assert "signed=secret" not in dialog._status.text()


def test_invoice_collector_dialog_loads_catalog_and_requires_active_connections(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog._provider.count() == 18
    dialog._set_folder(tmp_path)
    dialog._fetch_active()
    assert "Keine aktiven Provider-Verbindungen" in dialog._status.text()


def test_graph_mailbox_action_is_enabled_only_for_mail_routes(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    provider = next(
        item for item in dialog._catalog.providers
        if item.provider_id == "mollie_fees"
    )
    dialog._provider.setCurrentIndex(dialog._provider.findData(provider.provider_id))
    mail_index = next(
        index for index in range(dialog._route.count())
        if dialog._route.itemData(index).method == "mail"
    )
    api_index = next(
        index for index in range(dialog._route.count())
        if dialog._route.itemData(index).method == "official_api"
    )

    dialog._route.setCurrentIndex(mail_index)
    assert dialog._mail_test_button.isEnabled()
    assert not dialog._mailbox.isHidden()
    assert not dialog._sender_domains.isHidden()
    assert not dialog._mailbox_label.isHidden()
    assert not dialog._sender_domains_label.isHidden()
    assert dialog._api_token.isHidden()

    dialog._route.setCurrentIndex(api_index)
    assert not dialog._mail_test_button.isEnabled()
    assert dialog._mailbox.isHidden()
    assert dialog._sender_domains.isHidden()
    assert dialog._mailbox_label.isHidden()
    assert dialog._sender_domains_label.isHidden()
    assert not dialog._api_token.isHidden()


def test_provider_portal_menu_opens_only_https_hosts_from_catalog(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    opened: list[str] = []
    monkeypatch.setattr(
        dialog_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    dialog._provider.setCurrentIndex(dialog._provider.findData("codescene"))

    assert dialog._portal_button.isEnabled()
    assert [action.text() for action in dialog._portal_menu.actions()] == [
        "codescene.com",
        "billing.stripe.com",
    ]
    dialog._portal_menu.actions()[1].trigger()
    assert opened == ["https://billing.stripe.com/"]
    assert "bleiben manuell" in dialog._status.text()

    dialog._open_provider_portal("https://attacker.example.test/path")
    assert opened == ["https://billing.stripe.com/"]
    assert "nicht geöffnet" in dialog._status.text()
    dialog._open_provider_portal("127.0.0.1")
    assert opened == ["https://billing.stripe.com/"]


def test_invoice_collector_dialog_opens_only_an_existing_target_folder(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    opened: list[str] = []
    monkeypatch.setattr(
        dialog_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    dialog._set_folder(tmp_path)
    dialog._open_folder()

    assert [Path(value).resolve() for value in opened] == [tmp_path.resolve()]
    assert "Cloud-Syncstatus wird dadurch nicht bestätigt" in dialog._status.text()

    dialog._folder.setText(str(tmp_path / "missing"))
    dialog._open_folder()
    assert [Path(value).resolve() for value in opened] == [tmp_path.resolve()]
    assert "nicht verfügbar" in dialog._status.text()


def test_review_folder_action_opens_only_the_selected_tenant_review_directory(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    target = tmp_path / "onedrive"
    review_folder = target / "xw" / "_needs_review"
    review_folder.mkdir(parents=True)
    opened: list[Path] = []
    monkeypatch.setattr(
        dialog_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(Path(url.toLocalFile())) or True,
    )
    dialog._set_folder(target)

    dialog._open_review_folder()

    assert opened == [review_folder.resolve()]
    assert "manuell" in dialog._status.text()
    assert "nicht bestätigt" in dialog._status.text()

    dialog._tenant.setCurrentIndex(dialog._tenant.findData("wuedara"))
    dialog._open_review_folder()
    assert opened == [review_folder.resolve()]
    assert "keine Prüfablage" in dialog._status.text()

    dialog._folder.clear()
    dialog._open_review_folder()
    assert opened == [review_folder.resolve()]
    assert "Zielordner auswählen" in dialog._status.text()


def test_dialog_resolves_review_pdf_after_explicit_date_and_type_confirmation(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    target = tmp_path / "onedrive"
    target.mkdir()
    journal = InvoiceJournal(tmp_path / "review-journal.sqlite3")
    connection = ProviderConnection.create(
        provider_id="fixture",
        tenant_id=TenantId.XW,
        account_alias="billing",
        enabled=False,
    )
    source = tmp_path / "unknown-date.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Invoice, date unclear")
        pdf.save(source)
    sink = OneDriveLocalSink(target)
    candidate = DocumentCandidate(
        connection=connection,
        route_key="mail_pdf",
        source_id="message-1:attachment-1",
        external_id="message-1:attachment-1",
        document_type=DocumentType.UNKNOWN,
        original_filename=source.name,
    )
    DocumentPipeline(sink=sink, journal=journal).process(
        DownloadedArtifact(candidate, source)
    )
    review = journal.list_review_documents(tenant_id="xw", sink_id=sink.sink_id)[0]
    review_path = sink.target_path_for(review.relative_path)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(review_path), "PDF-Dateien (*.pdf)"),
    )
    monkeypatch.setattr(
        dialog_module.QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("2026-11-07", True),
    )
    monkeypatch.setattr(
        dialog_module.QInputDialog,
        "getItem",
        lambda *_args, **_kwargs: (DocumentType.EXPENSE_INVOICE.value, True),
    )
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
        invoice_journal=journal,
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._set_folder(target)

    monkeypatch.setattr(
        dialog_module.QInputDialog,
        "getItem",
        lambda *_args, **_kwargs: ("Belegart auswählen …", True),
    )
    dialog._resolve_review_file()
    assert review_path.is_file()
    assert dialog._table.rowCount() == 0
    assert "konkrete Belegart" in dialog._status.text()

    monkeypatch.setattr(
        dialog_module.QInputDialog,
        "getItem",
        lambda *_args, **_kwargs: (DocumentType.EXPENSE_INVOICE.value, True),
    )
    dialog._resolve_review_file()
    qtbot.waitUntil(lambda: dialog._review_worker is None, timeout=3000)  # type: ignore[attr-defined]

    assert not review_path.exists()
    assert dialog._table.rowCount() == 1
    assert "REVIEW_RESOLVED; SYNC_PENDING" in dialog._table.item(0, 4).text()
    assert "Prüfkopie entfernt" in dialog._status.text()


def test_invoice_collector_dialog_saves_unverified_route_as_disabled_draft(
    qtbot: object, tmp_path: Path
) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    dialog = InvoiceCollectorDialog(tenant_id="xw", connection_repository=repository)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    provider = next(
        provider for provider in dialog._catalog.providers
        if any(route.method == "mail" for route in provider.routes)
    )
    route = next(route for route in provider.routes if route.method == "mail")
    dialog._provider.setCurrentIndex(dialog._provider.findData(provider.provider_id))
    dialog._route.setCurrentIndex(
        next(
            index for index in range(dialog._route.count())
            if dialog._route.itemData(index).route_key == route.route_key
        )
    )
    dialog._account_alias.setText("billing")
    dialog._mailbox.setText("billing@example.test")
    dialog._sender_domains.setText("invoices.example.test")
    dialog._save_connection()
    assert repository.list_enabled() == []
    connections, issues = repository.list_all_with_issues()
    assert issues == []
    assert len(connections) == 1
    assert connections[0].enabled is False
    assert connections[0].route_settings[0].options["mailbox"] == "billing@example.test"
    assert "deaktivierter Entwurf" in dialog._status.text()


def test_saved_connection_can_be_loaded_but_unverified_route_stays_disabled(
    qtbot: object, tmp_path: Path
) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    catalog_path = (
        Path(__file__).resolve().parents[2]
        / "markdowns"
        / "rechnungsautomat_ausgabenpruefung_2026-11"
        / "PROVIDER_REGISTRY.yaml"
    )
    catalog = dialog_module.ProviderCatalog.from_yaml(catalog_path)
    mail_provider = next(
        provider for provider in catalog.providers
        if any(route.method == "mail" for route in provider.routes)
    )
    mail_route = next(route for route in mail_provider.routes if route.method == "mail")
    saved = ProviderConnection.create(
        provider_id=mail_provider.provider_id,
        tenant_id=TenantId.XW,
        account_alias="billing",
        enabled=False,
        route_settings=(
            RouteSettings(
                route_key=mail_route.route_key,
                options={
                    "mailbox": "billing@example.test",
                    "sender_domains": "invoices.example.test",
                    "document_type": "expense_invoice",
                },
            ),
        ),
    )
    repository.save(saved)

    dialog = InvoiceCollectorDialog(tenant_id="xw", connection_repository=repository)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._saved_connections.setCurrentIndex(
        dialog._saved_connections.findData(str(saved.connection_id))
    )

    assert dialog._account_alias.text() == "billing"
    assert dialog._mailbox.text() == "billing@example.test"
    assert dialog._sender_domains.text() == "invoices.example.test"
    assert dialog._provider.isEnabled() is False
    dialog._toggle_saved_connection()
    assert "live verifiziert" in dialog._status.text()
    assert repository.list_enabled() == []


def test_saving_an_existing_verified_connection_keeps_its_identity(
    qtbot: object, tmp_path: Path
) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    dialog = InvoiceCollectorDialog(tenant_id="xw", connection_repository=repository)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    catalog = dialog._catalog
    provider = next(
        provider for provider in catalog.providers
        if any(route.method == "mail" for route in provider.routes)
    )
    route = next(route for route in provider.routes if route.method == "mail")
    verified_provider = replace(
        provider,
        routes=tuple(
            replace(item, maturity="verified") if item.route_key == route.route_key else item
            for item in provider.routes
        ),
    )
    dialog._catalog = replace(
        catalog,
        providers=tuple(verified_provider if item.provider_id == provider.provider_id else item
                        for item in catalog.providers),
    )
    dialog._provider.setCurrentIndex(dialog._provider.findData(provider.provider_id))
    dialog._provider_changed()
    dialog._account_alias.setText("billing")
    dialog._mailbox.setText("billing@example.test")
    dialog._sender_domains.setText("invoices.example.test")
    dialog._save_connection()
    first = repository.list_enabled()[0]
    repository.save(
        replace(
            first,
            route_settings=first.route_settings
            + (RouteSettings(route_key="future_route", enabled=False),),
        )
    )
    dialog._load_saved_connections(select_id=str(first.connection_id))

    dialog._mailbox.setText("ap@example.test")
    dialog._save_connection()
    second = repository.list_enabled()[0]

    assert second.connection_id == first.connection_id
    assert second.route_settings[0].options["mailbox"] == "ap@example.test"
    assert second.route_settings[1].route_key == "future_route"
    repository.save(replace(second, enabled=False))
    dialog._load_saved_connections(select_id=str(first.connection_id))
    dialog._mailbox.setText("billing2@example.test")
    dialog._save_connection()
    third = repository.list_all_with_issues()[0][0]
    assert third.enabled is False
    assert third.route_settings[0].options["mailbox"] == "billing2@example.test"


def test_api_token_is_saved_only_through_secret_store(
    qtbot: object, tmp_path: Path
) -> None:
    class MemorySecretStore:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def get(self, secret_ref: str) -> str:
            return self.values[secret_ref]

        def set(self, secret_ref: str, value: str) -> None:
            self.values[secret_ref] = value

    secrets = MemorySecretStore()
    journal_path = tmp_path / "connections.sqlite3"
    repository = ConnectionRepository(journal_path)
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=repository,
        secret_store=secrets,
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    provider = next(
        provider for provider in dialog._catalog.providers
        if any(route.method == "official_api" for route in provider.routes)
    )
    route = next(route for route in provider.routes if route.method == "official_api")
    dialog._provider.setCurrentIndex(dialog._provider.findData(provider.provider_id))
    route_index = next(
        index for index in range(dialog._route.count())
        if dialog._route.itemData(index).route_key == route.route_key
    )
    dialog._route.setCurrentIndex(route_index)
    dialog._account_alias.setText("fees")
    assert "invoices.read" in dialog._api_token_label.text()
    dialog._api_token.setText("test-sensitive-api-token")
    dialog._save_connection()

    saved, issues = repository.list_all_with_issues()
    assert issues == []
    assert len(saved) == 1
    assert saved[0].enabled is False
    secret_ref = saved[0].route_settings[0].secret_ref
    assert secret_ref is not None
    assert secret_ref in secrets.values
    assert b"test-sensitive-api-token" not in journal_path.read_bytes()
    assert secrets.values[secret_ref] == "test-sensitive-api-token"
    assert "deaktivierter Entwurf" in dialog._status.text()


def test_invoice_collector_dialog_does_not_save_provider_without_automated_route(
    qtbot: object, tmp_path: Path
) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    dialog = InvoiceCollectorDialog(tenant_id="xw", connection_repository=repository)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    index = dialog._provider.findData("codescene")
    dialog._provider.setCurrentIndex(index)
    dialog._save_connection()
    assert repository.list_enabled() == []
    assert "keine automatisierte Route" in dialog._status.text()


def test_mailbox_and_sender_domain_settings_are_validated_locally() -> None:
    assert _looks_like_mailbox("billing@example.com")
    assert not _looks_like_mailbox("billing-at-example.com")
    assert _parse_sender_domains("@billing.example, invoices.vendor.example") == frozenset(
        {"billing.example", "invoices.vendor.example"}
    )
    assert _parse_sender_domains("trusted.example, https://bad.example") == frozenset()


def test_collection_results_show_route_outcomes_without_external_ids(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    result = CollectionRun(
        summary=CollectionSummary(
            items=(
                CollectionItemResult(
                    source_id="private-external-id",
                    outcome=DocumentOutcome.NEW,
                    route_key="mail_pdf",
                    provider_id="browserstack",
                    tenant_id="xw",
                    account_alias="billing",
                    display_name="invoice.pdf",
                ),
                CollectionItemResult(
                    source_id="another-private-id",
                    error="AUTH_REQUIRED: Anmeldung nötig",
                    route_key="mail_pdf",
                    provider_id="browserstack",
                    tenant_id="xw",
                    account_alias="billing",
                ),
                CollectionItemResult(
                    source_id="conflicted-private-id",
                    outcome=DocumentOutcome.CONTENT_CONFLICT,
                    route_key="api",
                    provider_id="mollie_fees",
                    tenant_id="wuedara",
                    account_alias="fees",
                    display_name="invoice-2026.pdf",
                ),
                CollectionItemResult(
                    source_id="duplicate-private-id",
                    outcome=DocumentOutcome.ALREADY_PRESENT,
                    route_key="mail_pdf",
                    provider_id="figma",
                    tenant_id="xw",
                    account_alias="design",
                    display_name="figma-invoice.pdf",
                    provenance=("figma/mail_pdf", "mollie_fees/invoices_api"),
                ),
            )
        ),
        issues=(
            ConnectionRouteIssue(
                connection_id="connection-id",
                route_key="api",
                message="UNSUPPORTED_ACCOUNT: Route nicht verifiziert",
                provider_id="mollie_fees",
                tenant_id="wuedara",
                account_alias="fees",
            ),
        ),
    )

    dialog._on_collection_finished(0, result)

    assert dialog._table.columnCount() == 6
    assert dialog._table.rowCount() == 5
    assert dialog._table.item(0, 0).text() == "browserstack / billing"
    assert dialog._table.item(0, 1).text() == "mail_pdf"
    assert dialog._table.item(0, 4).text() == "NEW"
    assert dialog._table.item(1, 4).text() == "AUTH_REQUIRED: Anmeldung nötig"
    assert dialog._table.item(2, 4).text() == "CONTENT_CONFLICT"
    assert dialog._table.item(3, 4).text() == "ALREADY_PRESENT"
    assert dialog._table.item(3, 5).text() == "figma/mail_pdf · mollie_fees/invoices_api"
    assert dialog._table.item(4, 4).text().startswith("UNSUPPORTED_ACCOUNT:")
    visible_text = " ".join(
        dialog._table.item(row, column).text()
        for row in range(dialog._table.rowCount())
        for column in range(dialog._table.columnCount())
    )
    assert "private-external-id" not in visible_text
    assert "another-private-id" not in visible_text
    assert "private-api-resource-id" not in visible_text


def test_collection_results_distinguish_empty_route_from_success(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    result = CollectionRun(
        summary=CollectionSummary(
            items=(
                CollectionItemResult(
                    source_id="opaque-connection",
                    route_key="mail_pdf",
                    provider_id="browserstack",
                    tenant_id="xw",
                    account_alias="billing",
                ),
            )
        )
    )

    dialog._on_collection_finished(0, result)

    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 4).text() == "Keine passenden Dokumente"
    assert dialog._status.text() == "Abruf abgeschlossen; keine passenden Dokumente gefunden."


def test_retry_action_targets_only_routes_that_failed_last_run(
    qtbot: object, monkeypatch: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    result = CollectionRun(
        summary=CollectionSummary(
            (
                CollectionItemResult(
                    source_id="opaque-one",
                    route_key="mail_pdf",
                    connection_id="connection-one",
                    provider_id="browserstack",
                    tenant_id="xw",
                    account_alias="billing",
                    error="AUTH_REQUIRED: Anmeldung erforderlich",
                ),
                CollectionItemResult(
                    source_id="opaque-two",
                    route_key="mail_pdf",
                    connection_id="connection-two",
                    provider_id="figma",
                    tenant_id="xw",
                    account_alias="billing",
                    error="OUT_OF_PERIOD: outside selected period",
                ),
                CollectionItemResult(
                    source_id="opaque-three",
                    route_key="browser_portal",
                    connection_id="connection-three",
                    provider_id="github",
                    tenant_id="xw",
                    account_alias="billing",
                    error="POLICY_BLOCKED: Portalzugriff nicht freigegeben",
                ),
                CollectionItemResult(
                    source_id="opaque-four",
                    route_key="api_invoice",
                    connection_id="connection-four",
                    provider_id="mollie_fees",
                    tenant_id="xw",
                    account_alias="billing",
                    error="CONTENT_CONFLICT: externe ID mit anderem Inhalt",
                ),
            )
        ),
        issues=(
            ConnectionRouteIssue(
                connection_id="connection-five",
                route_key="mail_pdf",
                message="UNSUPPORTED_ACCOUNT: Route ist nicht verifiziert",
            ),
            ConnectionRouteIssue(
                connection_id="connection-six",
                route_key="mail_pdf",
                message="TRANSIENT_NETWORK: Anbieter vorübergehend nicht erreichbar",
            ),
        ),
    )
    dialog._on_collection_finished(0, result)
    requested: list[set[tuple[str, str]] | None] = []
    monkeypatch.setattr(
        dialog,
        "_fetch_active",
        lambda: requested.append(dialog._pending_retry_targets),
    )

    assert dialog._retry_button.isEnabled()
    dialog._retry_failed_routes()

    expected = {
        ("connection-one", "mail_pdf"),
        ("connection-six", "mail_pdf"),
    }
    assert requested == [expected]
    assert dialog._pending_retry_targets == expected


def test_run_history_shows_route_status_and_reuses_selected_period(
    qtbot: object, tmp_path: Path
) -> None:
    journal = InvoiceJournal(tmp_path / "run-history.sqlite3")
    period = DateRange(date(2026, 10, 1), date(2026, 10, 31))
    run_id, _resumed = journal.begin_or_resume_run(
        period=period,
        target_fingerprint="opaque-target",
        connection_fingerprints={"connection-id": "opaque-fingerprint"},
    )
    journal.record_route_status(
        run_id=run_id,
        connection_id="connection-id",
        route_key="mail_pdf",
        status="WAITING_FOR_USER",
        error_code="AUTH_REQUIRED",
    )
    journal.record_checkpoint(
        run_id=run_id,
        connection_id="connection-id",
        route_key="mail_pdf",
        source_id="opaque-source-id",
    )
    dialog = InvoiceRunHistoryDialog(journal)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    assert dialog._runs_table.rowCount() == 1
    assert dialog._runs_table.item(0, 1).text() == "RUNNING"
    assert dialog._routes_table.rowCount() == 1
    assert dialog._routes_table.item(0, 1).text() == "mail_pdf"
    assert dialog._routes_table.item(0, 2).text() == "WAITING_FOR_USER: AUTH_REQUIRED"
    assert dialog._routes_table.item(0, 3).text() == "1"
    assert dialog._use_period_button.isEnabled()

    dialog._use_period_button.click()

    assert dialog.selected_period == (period.start, period.end)


def test_collector_run_history_applies_period_and_starts_fetch(
    qtbot: object, monkeypatch: object, tmp_path: Path
) -> None:
    journal = InvoiceJournal(tmp_path / "run-history-action.sqlite3")
    run_period = DateRange(date(2026, 9, 1), date(2026, 9, 30))
    journal.begin_or_resume_run(
        period=run_period,
        target_fingerprint="opaque-target",
        connection_fingerprints={"connection-id": "opaque-fingerprint"},
    )
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
        invoice_journal=journal,
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    fetches: list[bool] = []
    monkeypatch.setattr(dialog, "_fetch_active", lambda: fetches.append(True))

    def accept_history(history: InvoiceRunHistoryDialog) -> int:
        history.selected_period = (run_period.start, run_period.end)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(InvoiceRunHistoryDialog, "exec", accept_history)

    dialog._show_run_history()

    assert dialog._period_start.date() == QDate(2026, 9, 1)
    assert dialog._period_end.date() == QDate(2026, 9, 30)
    assert fetches == [True]


def test_collection_service_uses_the_dialog_journal(
    qtbot: object, monkeypatch: object, tmp_path: Path
) -> None:
    journal = InvoiceJournal(tmp_path / "injected-journal.sqlite3")
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
        invoice_journal=journal,
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    target = tmp_path / "target"
    dialog._folder.setText(str(target))
    monkeypatch.setattr(dialog_module, "build_connector_factories", lambda **_kwargs: object())

    service = dialog._build_collection_service()

    assert service.journal is journal
    assert service.target_root == target


def test_manual_import_runs_in_worker_and_publishes_partial_results_on_cancel(
    qtbot: object, monkeypatch, tmp_path: Path
) -> None:
    started = Event()
    release = Event()
    captured_periods = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(tmp_path / "fixture.pdf")], ""),
    )

    def blocked_import(**kwargs: object) -> list[tuple[str, str, str, str]]:
        captured_periods.append(kwargs["period"])
        started.set()
        release.wait(2)
        return [("fixture", "xw", "fixture.pdf", "NEW")]

    monkeypatch.setattr(dialog_module, "_run_manual_import", blocked_import)
    target = tmp_path / "onedrive"
    target.mkdir()
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._set_folder(target)
    dialog._period_start.setDate(QDate(2026, 11, 1))
    dialog._period_end.setDate(QDate(2026, 11, 30))

    dialog._manual_import()

    qtbot.waitUntil(started.is_set, timeout=1500)  # type: ignore[attr-defined]
    assert dialog._manual_worker is not None
    assert dialog._manual_worker.isRunning()
    assert not dialog._fetch_button.isEnabled()
    dialog._manual_cancel_button.click()
    release.set()
    qtbot.waitUntil(lambda: dialog._manual_worker is None, timeout=3000)  # type: ignore[attr-defined]

    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 3).text() == "fixture.pdf"
    assert dialog._status.text().startswith("Import abgebrochen")
    assert len(captured_periods) == 1
    assert captured_periods[0].start.isoformat() == "2026-11-01"
    assert captured_periods[0].end.isoformat() == "2026-11-30"


def test_manual_import_displays_out_of_period_documents_as_skipped(
    qtbot: object, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(tmp_path / "old-invoice.pdf")], ""),
    )
    monkeypatch.setattr(
        dialog_module,
        "_run_manual_import",
        lambda **_kwargs: [("fixture", "xw", "old-invoice.pdf", "OUT_OF_PERIOD")],
    )
    target = tmp_path / "onedrive"
    target.mkdir()
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._set_folder(target)

    dialog._manual_import()

    qtbot.waitUntil(lambda: dialog._manual_worker is None, timeout=3000)  # type: ignore[attr-defined]
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 4).text() == "Außerhalb des gewählten Zeitraums"
    assert "1 außerhalb Zeitraum" in dialog._status.text()
