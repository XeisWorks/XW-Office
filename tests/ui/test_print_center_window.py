"""Separate entry point and immutable official-product UI."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from xw_office.core.config import PrintingSection
from xw_office.print_center.article_dialog import ArticleDialog
from xw_office.print_center.models import PrintArticle
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
    assert not window.print_button.isEnabled()
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
