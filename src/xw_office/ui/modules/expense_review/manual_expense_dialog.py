from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox, QWidget,
)

from xw_office.services.expenses.xw_flow_expense_client import XwFlowExpenseClient
from xw_office.services.expenses.service import ExpensePositionView, WUEDARA_EXPENSE_POSITION


class ManualExpenseDialog(QDialog):
    def __init__(
        self, client: XwFlowExpenseClient, tenant_key: str,
        positions: list[ExpensePositionView], parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._tenant_key = tenant_key
        self._positions = positions
        self.setWindowTitle("Neue zusätzliche Ausgabe")
        layout = QFormLayout(self)
        self.category = QComboBox()
        for position in positions:
            self.category.addItem(f"{position.initials} · {position.label}", position)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("z. B. 24,90")
        self.expense_date = QLineEdit(date.today().isoformat())
        self.recipient = QLineEdit()
        self.purpose = QLineEdit()
        self.tax = QComboBox()
        self.tax.addItem("unbekannt", None)
        for rate in (0, 10, 13, 20):
            self.tax.addItem(f"{rate} %", rate * 100)
        self.payment = QComboBox()
        for key, label in (
            ("private_card", "Private Kreditkarte"),
            ("private_cash", "Privat bar"),
            ("private_account", "Privates Konto"),
            ("business_cash", "Betriebskasse"),
            ("other", "Sonstige"),
        ):
            self.payment.addItem(label, key)
        self.note = QLineEdit()
        if tenant_key == "xw":
            layout.addRow("Kategorie", self.category)
        else:
            self.category.hide()
        layout.addRow("Brutto EUR", self.amount)
        layout.addRow("Datum", self.expense_date)
        layout.addRow("Empfänger", self.recipient)
        layout.addRow("Zweck", self.purpose)
        layout.addRow("USt.", self.tax)
        layout.addRow("Zahlungsart", self.payment)
        layout.addRow("Notiz", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _save(self) -> None:
        try:
            amount = Decimal(self.amount.text().strip().replace(",", "."))
            expense_date = date.fromisoformat(self.expense_date.text().strip())
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Ausgabe", "Bitte Betrag und Datum korrekt eingeben.")
            return
        recipient = self.recipient.text().strip()
        purpose = self.purpose.text().strip()
        if amount <= 0 or not (recipient or purpose):
            QMessageBox.warning(self, "Ausgabe", "Betrag sowie Empfänger oder Zweck sind erforderlich.")
            return
        position = (
            WUEDARA_EXPENSE_POSITION if self._tenant_key == "wuedara"
            else self.category.currentData()
        )
        if not isinstance(position, ExpensePositionView):
            QMessageBox.warning(self, "Ausgabe", "Bitte eine Kategorie wählen.")
            return
        try:
            self._client.create(
                tenant_key=self._tenant_key,
                category_key=position.key,
                category_label=position.label,
                amount=amount,
                expense_date=expense_date,
                recipient=recipient,
                purpose=purpose,
                tax_rate_bps=self.tax.currentData(),
                payment_source=str(self.payment.currentData()),
                note=self.note.text().strip(),
            )
        except Exception as exc:  # noqa: BLE001 - dialog must show bridge errors
            QMessageBox.warning(self, "Ausgabe konnte nicht gespeichert werden", str(exc))
            return
        self.accept()
