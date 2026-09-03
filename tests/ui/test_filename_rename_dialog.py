from __future__ import annotations

from PySide6.QtCore import Qt

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.services.filename_generator.service import FilenameGeneratorService
from xw_office.ui.modules.layout.filename_rename_dialog import FilenameRenamePanel
from xw_office.ui.modules.layout.view import LayoutView


def test_dialog_scans_example_and_preselects_safe_row(qtbot, tmp_path) -> None:
    (tmp_path / "03.2 Es geht Aufwärts TIEF-BTB.mp3").write_bytes(b"audio")
    panel = FilenameRenamePanel(FilenameGeneratorService())
    qtbot.addWidget(panel)
    panel._preset_combo.setCurrentIndex(2)  # noqa: SLF001 - UI smoke test
    panel._folder_edit.setText(str(tmp_path))  # noqa: SLF001

    panel._scan()  # noqa: SLF001

    assert panel._table.rowCount() == 1  # noqa: SLF001
    assert panel._table.item(0, panel.COL_TARGET).text() == "sk-t__03__btb__teacher.mp3"  # noqa: SLF001
    assert panel._table.item(0, panel.COL_SELECT).checkState() == Qt.CheckState.Checked  # noqa: SLF001
    assert panel._rename_button.isEnabled()  # noqa: SLF001


def test_panel_allows_manual_completion_of_unrecognized_name(qtbot, tmp_path) -> None:
    (tmp_path / "mein unklarer Track.mp3").write_bytes(b"audio")
    panel = FilenameRenamePanel(FilenameGeneratorService())
    qtbot.addWidget(panel)
    panel._folder_edit.setText(str(tmp_path))  # noqa: SLF001

    panel._scan()  # noqa: SLF001
    panel._table.item(0, panel.COL_TRACK).setText("3")  # noqa: SLF001
    panel._table.item(0, panel.COL_EDITION).setText("sk-t")  # noqa: SLF001
    panel._table.item(0, panel.COL_INSTRUMENT).setText("btb")  # noqa: SLF001
    panel._table.item(0, panel.COL_ROLE).setText("teacher")  # noqa: SLF001

    assert panel._table.item(0, panel.COL_TARGET).text() == "sk-t__03__btb__teacher.mp3"  # noqa: SLF001
    assert panel._table.item(0, panel.COL_SELECT).checkState() == Qt.CheckState.Checked  # noqa: SLF001


def test_layout_keeps_generator_and_rename_panel_in_one_register(qtbot) -> None:
    container = Container(AppConfig())
    register_default_services(container)
    view = LayoutView(container)
    qtbot.addWidget(view)

    assert view.findChild(FilenameRenamePanel) is not None
