from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QPushButton

from xw_office.ui.modules.taxes.result_dialog import OperationResultDialog


def test_result_dialog_toggles_technical_details(qtbot: object) -> None:
    dialog = OperationResultDialog(
        None,
        tone="error",
        title="Fehler",
        summary="Vorgang fehlgeschlagen",
        details="Diagnosedetails",
    )
    qtbot.addWidget(dialog)
    toggle = dialog.findChild(QPushButton)
    details = dialog.findChild(QPlainTextEdit)

    assert toggle is not None
    assert details is not None
    assert details.isHidden()

    toggle.click()
    assert not details.isHidden()
    assert toggle.text() == "Technische Details ausblenden"

    toggle.click()
    assert details.isHidden()
    assert toggle.text() == "Technische Details anzeigen"
