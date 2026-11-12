from __future__ import annotations

from PySide6.QtCore import Qt

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.ui.home_view import DashboardCard, HomeView


def test_dashboard_card_emits_navigation_for_left_click(qtbot) -> None:
    container = Container(AppConfig())
    signals = AppSignals()
    container.register(AppSignals, lambda _container: signals)
    view = HomeView(container)
    qtbot.addWidget(view)
    navigated: list[str] = []
    signals.navigate_to_module.connect(navigated.append)
    card = view.findChild(DashboardCard)
    assert card is not None

    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

    assert navigated == [ModuleKey.RECHNUNGEN.value]
