from __future__ import annotations

from pathlib import Path

from xw_office.core.app_paths import default_invoice_target_dir
from xw_office.services.invoice_collection.connections import ConnectionRepository
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
