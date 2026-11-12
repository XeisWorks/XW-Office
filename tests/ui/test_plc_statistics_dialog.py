from __future__ import annotations

from threading import Event

from PySide6.QtCore import QTimer

from xw_office.services.plc.statistics import PlcStatisticsService
from xw_office.ui.modules.rechnungen.plc_statistics_dialog import PlcStatisticsDialog


def test_statistics_service_resolution_runs_off_ui_thread(qtbot) -> None:
    entered = Event()
    release = Event()

    class Service:
        def load(self):
            return ()

    class SlowContainer:
        def resolve(self, service_type: object) -> object:
            assert service_type is PlcStatisticsService
            entered.set()
            release.wait(2)
            return Service()

    dialog = PlcStatisticsDialog(SlowContainer())  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    heartbeats: list[bool] = []
    QTimer.singleShot(20, lambda: heartbeats.append(True))
    qtbot.waitUntil(entered.is_set, timeout=1000)
    qtbot.waitUntil(lambda: bool(heartbeats), timeout=1000)
    assert dialog._status.text() == "Lade PLC-Statistik …"  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001
    assert dialog._status.text().startswith("Post-Export")  # noqa: SLF001
