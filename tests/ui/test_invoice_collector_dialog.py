from __future__ import annotations

from pathlib import Path

from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.ui.modules.expense_review.invoice_collector_dialog import InvoiceCollectorDialog


def test_invoice_collector_dialog_loads_catalog_and_requires_active_connections(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = InvoiceCollectorDialog(
        tenant_id="xw",
        connection_repository=ConnectionRepository(tmp_path / "connections.sqlite3"),
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog._provider.count() == 15
    dialog._set_folder(tmp_path)
    dialog._fetch_active()
    assert "Keine aktiven Provider-Verbindungen" in dialog._status.text()


def test_invoice_collector_dialog_saves_selected_route_with_connection(qtbot: object, tmp_path: Path) -> None:
    repository = ConnectionRepository(tmp_path / "connections.sqlite3")
    dialog = InvoiceCollectorDialog(tenant_id="xw", connection_repository=repository)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._account_alias.setText("billing")
    dialog._save_connection()
    connections = repository.list_enabled()
    assert len(connections) == 1
    assert connections[0].route_settings
    assert connections[0].route_settings[0].options["connector"]
