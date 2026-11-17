"""One-click dispatch planning at the start of an invoice run."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from xw_office.services.invoice_processing.shipping_plan import (
    ShippingCandidate, abroad_with_at_default,
)


_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class ShippingDateDialog(QDialog):
    dates_chosen = Signal(str, str)

    def __init__(self, parent: QWidget | None = None, *, today: date | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Voraussichtlicher Versand")
        self.setMinimumWidth(550)
        self._today = today or datetime.now(ZoneInfo("Europe/Vienna")).date()
        self._at_date = ""
        self._abroad_count = 0
        self._pending_count = 0
        layout = QVBoxLayout(self)
        self._info = QLabel("Sendungen werden ermittelt …")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)
        self._at_label = QLabel("Wann werden die Noten voraussichtlich versendet?")
        layout.addWidget(self._at_label)
        self._at_buttons = self._calendar_row(layout, self._choose_at)
        self._together = QCheckBox("Ausland mit Österreich/PLC versenden")
        self._together.setToolTip("Bei weniger als drei EU/CH-Sendungen ist getrennt voreingestellt.")
        self._together.hide()
        layout.addWidget(self._together)
        self._abroad_label = QLabel("Versanddatum für Ausland wählen:")
        self._abroad_label.hide()
        layout.addWidget(self._abroad_label)
        self._abroad_buttons = self._calendar_row(layout, self._choose_abroad)
        for button in self._abroad_buttons:
            button.hide()
        for button in self._at_buttons:
            button.setEnabled(False)

    def _calendar_row(self, layout: QVBoxLayout, callback: object) -> list[QPushButton]:
        row = QHBoxLayout()
        buttons: list[QPushButton] = []
        for offset in range(5):
            day = self._today + timedelta(days=offset)
            button = QPushButton(f"{_WEEKDAYS[day.weekday()]}\n{day:%d.%m.%Y}")
            button.setMinimumHeight(56)
            button.clicked.connect(lambda _checked=False, selected=day: callback(selected))
            row.addWidget(button)
            buttons.append(button)
        layout.addLayout(row)
        return buttons

    def set_shipments(
        self,
        candidates: list[ShippingCandidate],
        pending: list[dict[str, str]],
    ) -> None:
        at_count = sum(row.lane == "at" for row in candidates)
        self._abroad_count = sum(row.lane == "abroad" for row in candidates)
        self._pending_count = len(pending)
        digital_count = sum(row.lane == "digital" for row in candidates)
        eu_count = sum(row.eu_ch for row in candidates if row.lane == "abroad")
        third_country_count = self._abroad_count - eu_count
        plc_count = sum(row.plc and row.lane == "at" for row in candidates)
        self._info.setText(
            f"Dieser Lauf: {at_count} Österreich/PLC (davon {plc_count} PLC), "
            f"{self._abroad_count} Ausland (davon {eu_count} EU/CH, "
            f"{third_country_count} übriges Ausland). "
            f"Aus früheren Läufen warten {self._pending_count} Auslandssendungen. "
            f"{digital_count} rein digitale Lieferungen sind ausgenommen."
        )
        self._together.setVisible(bool(self._abroad_count or self._pending_count))
        self._together.setChecked(abroad_with_at_default(candidates, pending))
        for button in self._at_buttons:
            button.setEnabled(True)

    def _choose_at(self, day: date) -> None:
        self._at_date = day.isoformat()
        if (self._abroad_count or self._pending_count) and not self._together.isChecked():
            self._at_label.setText(f"Österreich/PLC: {day:%d.%m.%Y}")
            self._abroad_label.show()
            for button in self._abroad_buttons:
                button.show()
            return
        self._finish(self._at_date)

    def _choose_abroad(self, day: date) -> None:
        self._finish(day.isoformat())

    def _finish(self, abroad_date: str) -> None:
        self.dates_chosen.emit(self._at_date, abroad_date)
        self.accept()
