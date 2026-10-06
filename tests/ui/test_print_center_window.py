"""Separate entry point and immutable official-product UI."""
from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox, QSpinBox, QToolButton
from pytestqt.qtbot import QtBot

from xw_office.core.config import PrintingSection
from xw_office.print_center.article_dialog import ArticleDialog
from xw_office.print_center.details_dialog import PrintDetailsDialog
from xw_office.print_center.icons import printer_icon
from xw_office.print_center.models import PrintArticle, PrintReceipt, PrintStep
from xw_office.print_center.service import PrintCenterService
from xw_office.print_center.window import PrintCenterWindow


def test_official_readonly_and_own_editor_visibility(qtbot: QtBot) -> None:
    service = MagicMock(spec=PrintCenterService)
    service.printing_settings.return_value = PrintingSection()
    service.list_articles.return_value = [
        PrintArticle(id="office:ONE:", name="Offiziell", source="official", sku="ONE"),
        PrintArticle(id="own-id", name="Privat", source="own"),
    ]
    service.shutdown.return_value = True
    window = PrintCenterWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window._worker is None)
    assert window.table.rowCount() == 1
    window.table.selectRow(0)
    assert not window.new_button.isVisible()
    assert not window.edit_button.isVisible()
    assert not window.delete_button.isVisible()
    assert not window.table.cellWidget(0, 4).findChild(QToolButton, "article_print").isEnabled()
    assert not hasattr(window, "print_button")
    assert not hasattr(window, "preview_button")
    assert not hasattr(window, "favorite_button")
    assert not hasattr(window, "copies")
    window.tabs.setCurrentIndex(1)
    window.table.selectRow(0)
    assert window.table.isColumnHidden(2)
    assert window.new_button.isVisible()
    assert window.edit_button.isEnabled()
    assert window.delete_button.isEnabled()
    assert window.table.item(0, 2).text() == ""
    window.search.setText("not found")
    assert window.table.rowCount() == 0
    assert not window.edit_button.isEnabled()
    service.save_own.assert_not_called()
    service.delete_own.assert_not_called()
    service.print_article.assert_not_called()


def test_row_actions_target_their_article_without_selection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "xw_office.print_center.window.QSettings",
        lambda *args: QSettings(str(tmp_path / "favorites.ini"), QSettings.Format.IniFormat),
    )
    service = MagicMock(spec=PrintCenterService)
    service.printing_settings.return_value = PrintingSection()
    first = PrintArticle(
        id="office:A:", name="A", source="official", sku="A",
        pdf_path=r"C:\Druckdaten\Erster Titel.pdf", profile_id="noten_simplex",
    )
    second = PrintArticle(
        id="office:B:", name="B", source="official", sku="B",
        pdf_path=r"C:\Druckdaten\Zweiter Titel.pdf", profile_id="noten_simplex",
    )
    service.list_articles.return_value = [first, second]
    service.print_article.return_value = PrintReceipt(name="B", copies=7, job_ids=("confirmed",))
    service.shutdown.return_value = True
    window = PrintCenterWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window._worker is None)
    assert window.table.horizontalHeaderItem(0).text() == "★"
    assert window.table.horizontalHeaderItem(4).text() == "Aktionen"
    assert window.table.item(1, 3).text() == "Zweiter Titel.pdf"
    assert window.table.cellWidget(1, 0).text() == "☆"
    window.table.selectRow(0)
    preview = MagicMock()
    details = MagicMock()
    monkeypatch.setattr(window, "_preview", preview)
    monkeypatch.setattr(window, "_show_print_details", details)
    actions = window.table.cellWidget(1, 4)
    actions.findChild(QToolButton, "article_pdf").click()
    preview.assert_called_once_with(second)
    actions.findChild(QToolButton, "article_details").click()
    details.assert_called_once_with(second)
    actions.findChild(QSpinBox, "article_copies").setValue(7)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    actions.findChild(QToolButton, "article_print").click()
    qtbot.waitUntil(lambda: window._worker is None)
    service.print_article.assert_called_once_with(second, 7)
    window.table.cellWidget(1, 0).click()
    assert window.table.cellWidget(1, 0).text() == "★"
    window.favorite_only.setChecked(True)
    assert window.table.rowCount() == 1
    assert window.table.item(0, 1).text() == "B"
    window.table.cellWidget(0, 0).click()
    assert window.table.rowCount() == 0


def test_details_show_full_path_plan_and_profile_settings(qtbot: QtBot) -> None:
    printing = PrintingSection(print_profiles=[{
        "id": "score", "label": "Noten", "printer_name": "Canon",
        "backend": "pdf_xchange", "page_size": "A4", "orientation": "portrait",
        "scale_mode": "none", "scale_percent": 100.0, "x_offset_mm": 1.25,
        "native_pdf_exe": r"C:\PDF-XChange\PDFXEdit.exe",
    }])
    article = PrintArticle(
        id="office:ONE:", source="official", name="Noten",
        pdf_path=r"C:\Druckdaten\Noten.pdf",
        print_plan=(PrintStep(range="1-3", profile_id="score"),),
    )
    dialog = PrintDetailsDialog(article, printing)
    qtbot.addWidget(dialog)
    assert dialog.settings_text.isReadOnly()
    assert not hasattr(dialog, "edit_button")
    text = dialog.settings_text.toPlainText()
    for expected in (
        article.pdf_path, "1-3", "Canon", "pdf_xchange", "A4", "portrait",
        "Skalierung (%): 100.0", "Horizontaler Versatz (mm): 1.25",
        r"C:\PDF-XChange\PDFXEdit.exe",
    ):
        assert expected in text
    own = PrintDetailsDialog(article.model_copy(update={"source": "own", "sku": ""}), printing)
    qtbot.addWidget(own)
    assert own.settings_text.isReadOnly()
    own.edit_button.click()
    assert own.edit_requested
    assert not printer_icon().isNull()


def test_editor_rejects_official_article(qtbot: QtBot) -> None:
    with pytest.raises(ValueError, match="Offizielle"):
        ArticleDialog(
            PrintingSection(), PrintArticle(id="office:X:", name="X", source="official")
        )


def test_window_cannot_close_with_active_operation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock(spec=PrintCenterService)
    service.list_articles.return_value = []
    service.printing_settings.return_value = PrintingSection()
    service.shutdown.return_value = False
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    window = PrintCenterWindow(service)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window._worker is None)
    assert not window.close()
    service.shutdown.return_value = True
    assert window.close()
