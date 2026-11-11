"""Reason and optional reminder date for a persistent START hold."""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from xw_office.services.invoice_processing.start_holds import START_HOLD_REASONS, StartHold


class StartHoldDialog(QDialog):
    def __init__(self, *, invoice_label: str, existing: StartHold | None = None,
                 default_reason: str = "customer_question", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rechnung zurückstellen")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(invoice_label))
        form = QFormLayout()
        self._reason = QComboBox()
        for code, label in START_HOLD_REASONS.items():
            self._reason.addItem(label, code)
        reason = existing.reason if existing else default_reason
        index = self._reason.findData(reason)
        self._reason.setCurrentIndex(max(0, index))
        form.addRow("Grund", self._reason)
        self._note = QPlainTextEdit(existing.note if existing else "")
        self._note.setPlaceholderText("Optional: Was ist noch zu klären?")
        self._note.setMaximumHeight(85)
        form.addRow("Notiz", self._note)
        self._reminder = QCheckBox("Wiedervorlage")
        self._reminder.setChecked(bool(existing.review_on) if existing else True)
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("dd.MM.yyyy")
        saved_date = QDate.fromString(existing.review_on, "yyyy-MM-dd") if existing else QDate()
        self._date.setDate(saved_date if saved_date.isValid() else QDate.currentDate().addDays(7))
        self._date.setEnabled(self._reminder.isChecked())
        self._reminder.toggled.connect(self._date.setEnabled)
        form.addRow(self._reminder, self._date)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("ZURÜCKSTELLEN")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def reason(self) -> str:
        return str(self._reason.currentData() or "other")

    @property
    def note(self) -> str:
        return self._note.toPlainText().strip()

    @property
    def review_on(self) -> str:
        return self._date.date().toString("yyyy-MM-dd") if self._reminder.isChecked() else ""
