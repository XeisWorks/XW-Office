from __future__ import annotations

from PySide6.QtCore import Qt

from xw_office.services.filename_generator.service import FilenameGeneratorService
from xw_office.ui.modules.layout.filename_rename_dialog import FilenameRenameDialog


def test_dialog_scans_example_and_preselects_safe_row(qtbot, tmp_path) -> None:
    (tmp_path / "03.2 Es geht Aufwärts TIEF-BTB.mp3").write_bytes(b"audio")
    dialog = FilenameRenameDialog(FilenameGeneratorService())
    qtbot.addWidget(dialog)
    dialog._preset_combo.setCurrentIndex(2)  # noqa: SLF001 - UI smoke test
    dialog._folder_edit.setText(str(tmp_path))  # noqa: SLF001

    dialog._scan()  # noqa: SLF001

    assert dialog._table.rowCount() == 1  # noqa: SLF001
    assert dialog._table.item(0, dialog.COL_TARGET).text() == "sk-t__03__btb__teacher.mp3"  # noqa: SLF001
    assert dialog._table.item(0, dialog.COL_SELECT).checkState() == Qt.CheckState.Checked  # noqa: SLF001
    assert dialog._rename_button.isEnabled()  # noqa: SLF001
