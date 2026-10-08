from __future__ import annotations

from copy import deepcopy
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QTabWidget, QTextBrowser
from pytestqt.qtbot import QtBot

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.services.finanzonline import OssService, UvaService
from xw_office.services.finanzonline.oss_models import OssLine, OssQuarterResult
from xw_office.ui.modules.taxes.oss_presentation import oss_summary_html
from xw_office.ui.modules.taxes.oss_presentation import QuarterComboBox
from xw_office.ui.modules.taxes.presentation import CollapsibleDetails
from xw_office.ui.modules.taxes.view import TaxesView
from xw_office.ui.theme import apply_app_theme


@pytest.fixture
def tax_view(qtbot: QtBot) -> tuple[TaxesView, Mock]:
    uva = Mock(spec=UvaService)
    uva.describe_capabilities.return_value = "UVA test"
    oss = Mock(spec=OssService)
    oss.describe_capabilities.return_value = "OSS test"
    oss.calculate_quarter.return_value = OssQuarterResult(
        year=2026, quarter=3,
        goods_lines=[OssLine(
            country_code="DE", country_name="Germany", vat_rate="7.00",
            taxable_amount="100", tax_amount="7", source_docs=["test"],
        )],
    )
    oss.render_preview_text.return_value = "Technical test details"
    container = Mock(spec=Container)
    container.config = AppConfig()
    container.resolve.side_effect = lambda service: {UvaService: uva, OssService: oss}[service]
    view = TaxesView(cast(Container, container))
    qtbot.addWidget(view)
    view.resize(1150, 1000)
    view.show()
    return view, oss


def test_only_uva_and_oss_tabs_are_visible_and_no_expense_service_is_resolved(
    tax_view: tuple[TaxesView, Mock],
) -> None:
    view, _ = tax_view
    tabs = view.findChild(QTabWidget, "taxTabs")
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == ["UVA", "EU-OSS"]
    assert tabs.tabPosition() == QTabWidget.TabPosition.North
    assert tabs.tabBar().height() >= 40


@pytest.mark.parametrize("theme", ["dark_gold", "light_gold"])
def test_quarter_popup_text_fits_under_material_themes(
    qtbot: QtBot, qapp: QApplication, tax_view: tuple[TaxesView, Mock], theme: str,
) -> None:
    original = qapp.styleSheet()
    try:
        apply_app_theme(qapp, theme)
        view, _ = tax_view
        tabs = view.findChild(QTabWidget, "taxTabs")
        assert tabs is not None
        tabs.setCurrentIndex(1)
        quarter = view.findChild(QuarterComboBox, "ossQuarter")
        assert quarter is not None
        quarter.showPopup()
        qtbot.waitUntil(lambda: quarter.view().isVisible())
        qtbot.wait(250)
        for index in range(quarter.count()):
            rect = quarter.view().visualRect(quarter.model().index(index, 0))
            width = quarter.view().fontMetrics().horizontalAdvance(quarter.itemText(index))
            assert rect.width() >= width + 24
            assert rect.height() >= quarter.view().fontMetrics().height() + 12
            assert rect.top() >= 0
            assert rect.bottom() < quarter.view().viewport().height()
            if index:
                previous = quarter.view().visualRect(quarter.model().index(index - 1, 0))
                assert rect.top() > previous.bottom()
        assert [quarter.itemData(index) for index in range(quarter.count())] == [1, 2, 3, 4]
        quarter.hidePopup()
    finally:
        qapp.setStyleSheet(original)


def test_oss_summary_preserves_amounts_and_separates_goods_services() -> None:
    result = OssQuarterResult(
        year=2026, quarter=3,
        goods_lines=[OssLine(country_code="DE", country_name="<Germany>", vat_rate="7", taxable_amount="100", tax_amount="7")],
        service_lines=[OssLine(country_code="FR", country_name="France", vat_rate="20", taxable_amount="50", tax_amount="10", goods=False)],
    )
    original = deepcopy(result.model_dump())
    text = oss_summary_html(result)
    assert "EUR 17,00" in text
    assert "EUR 167,00" in text
    assert "EUR 150,00" in text
    assert "&lt;Germany&gt;" in text
    assert "(Waren)" in text and "(Leistungen)" in text
    assert result.model_dump() == original


def test_period_change_clears_stale_results_and_blocks_export(
    qtbot: QtBot, tax_view: tuple[TaxesView, Mock],
) -> None:
    view, _ = tax_view
    tabs = view.findChild(QTabWidget, "taxTabs")
    assert tabs is not None
    tabs.setCurrentIndex(1)
    preview = next(button for button in view.findChildren(QPushButton) if button.text() == "EU-OSS berechnen")
    export = next(button for button in view.findChildren(QPushButton) if button.text() == "EU-OSS XML speichern")
    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: view._oss_worker is None)
    summary = view.findChild(QTextBrowser, "ossSummary")
    quarter = view.findChild(QComboBox, "ossQuarter")
    assert summary is not None and quarter is not None
    assert "EUR 107,00" in summary.toPlainText()
    assert export.isEnabled()
    for detail in tabs.widget(1).findChildren(CollapsibleDetails):
        assert not detail.toggle.isChecked()
    quarter.setCurrentIndex((quarter.currentIndex() + 1) % 4)
    assert not export.isEnabled()
    assert summary.toPlainText() == ""


def test_oss_blocker_is_visible_even_with_details_collapsed(
    qtbot: QtBot, tax_view: tuple[TaxesView, Mock],
) -> None:
    view, oss = tax_view
    oss.calculate_quarter.return_value.blocking = ["Classification conflict"]
    tabs = view.findChild(QTabWidget, "taxTabs")
    assert tabs is not None
    tabs.setCurrentIndex(1)
    button = next(button for button in view.findChildren(QPushButton) if button.text() == "EU-OSS berechnen")
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: view._oss_worker is None)
    status = view.findChild(QLabel, "ossStatus")
    assert status is not None and "blockiert" in status.text()
    export = next(button for button in view.findChildren(QPushButton) if button.text() == "EU-OSS XML speichern")
    assert not export.isEnabled()
