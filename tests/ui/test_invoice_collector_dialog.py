from __future__ import annotations

from pathlib import Path

from xw_office.core.app_paths import default_invoice_target_dir
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import DocumentOutcome
from xw_office.services.invoice_collection.orchestrator import (
    CollectionItemResult,
    CollectionSummary,
)
from xw_office.services.invoice_collection.service import CollectionRun, ConnectionRouteIssue
from xw_office.ui.modules.expense_review.invoice_collector_dialog import (
    InvoiceCollectorDialog,
    _looks_like_mailbox,
    _parse_sender_domains,
)


def test_default_invoice_target_uses_current_windows_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Bernhard Holl"))
    assert default_invoice_target_dir() == (
        tmp_path / "Bernhard Holl" / "OneDrive - XeisWorks" / "00 Finanzmanagement" / "02 Belege"
    )


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


def test_invoice_collector_dialog_refuses_to_enable_unverified_route(qtbot: object, tmp_path: Path) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    dialog = InvoiceCollectorDialog(tenant_id="xw", connection_repository=repository)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._account_alias.setText("billing")
    dialog._save_connection()
    assert repository.list_enabled() == []
    assert "nicht live verifiziert" in dialog._status.text()


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

    assert dialog._table.columnCount() == 5
    assert dialog._table.rowCount() == 5
    assert dialog._table.item(0, 0).text() == "browserstack / billing"
    assert dialog._table.item(0, 1).text() == "mail_pdf"
    assert dialog._table.item(0, 4).text() == "NEW"
    assert dialog._table.item(1, 4).text() == "AUTH_REQUIRED: Anmeldung nötig"
    assert dialog._table.item(2, 4).text() == "CONTENT_CONFLICT"
    assert dialog._table.item(3, 4).text() == "ALREADY_PRESENT"
    assert dialog._table.item(4, 4).text().startswith("UNSUPPORTED_ACCOUNT:")
    visible_text = " ".join(
        dialog._table.item(row, column).text()
        for row in range(dialog._table.rowCount())
        for column in range(dialog._table.columnCount())
    )
    assert "private-external-id" not in visible_text
    assert "another-private-id" not in visible_text


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
