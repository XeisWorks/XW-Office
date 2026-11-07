from __future__ import annotations

from pathlib import Path

from xw_office.ui.modules.expense_review.invoice_collector_dialog import InvoiceCollectorDialog


def test_invoice_collector_dialog_loads_catalog_and_requires_active_connections(qtbot: object, tmp_path: Path) -> None:
    dialog = InvoiceCollectorDialog(tenant_id="xw")
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog._provider.count() == 15
    dialog._set_folder(tmp_path)
    dialog._fetch_active()
    assert "Keine aktiven Provider-Verbindungen" in dialog._status.text()
