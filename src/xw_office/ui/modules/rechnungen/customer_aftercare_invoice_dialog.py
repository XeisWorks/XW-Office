"""Zusatzrechnung-Preview/Bestätigung für Lieferkorrektur-Fälle (spec §8).

"Zusatzrechnung erstellen / Ohne Rechnung erledigen / Später" — the three
actions from spec §8. This dialog deliberately requires the user to
explicitly pick the sevDesk contact and confirm the billing country rather
than auto-resolving/auto-creating one: contact matching + address/country
resolution is a substantial, separate piece of logic that already exists in
a different shape for Wix-order invoices (DraftInvoiceService), and a
Lieferkorrektur case may not have a cleanly resolvable Wix order to derive
it from. A human confirming the two inputs the system can't determine with
confidence is the safer default for money-moving functionality.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.services.crm.types import ContactRecord
from xw_office.services.customer_aftercare.invoice_service import (
    CustomerAftercareInvoiceService,
    InvoiceCreationResult,
)
from xw_office.services.customer_aftercare.pricing_policy import CustomerAftercarePricingPolicy
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.services.sevdesk.contact_client import ContactClient

if TYPE_CHECKING:
    from xw_office.core.container import Container

_INVOICEABLE_ROLES = ("WRONG_DELIVERED", "CORRECTED_ORDER_ITEM", "SHIPPING")


class CustomerAftercareInvoiceDialog(QDialog):
    """Preview + confirm the Lieferkorrektur-Zusatzrechnung for one case."""

    def __init__(
        self,
        container: "Container",
        case: CustomerAftercareCase,
        items: list[CustomerAftercareItem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._case = case
        self._items = items
        self._aftercare: CustomerAftercareService = container.resolve(CustomerAftercareService)
        self._invoices: CustomerAftercareInvoiceService = container.resolve(CustomerAftercareInvoiceService)
        self._contacts_client: ContactClient = container.resolve(ContactClient)
        self._pricing = CustomerAftercarePricingPolicy(container.config.customer_aftercare)
        self._contacts: list[ContactRecord] = []
        self._contacts_worker: BackgroundWorker | None = None
        self._action_worker: BackgroundWorker | None = None
        self.action_taken: str = "later"
        self.created_invoice: InvoiceCreationResult | None = None
        self._build_ui()
        QTimer.singleShot(0, self._load_contacts)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._wait_for_workers()
        super().closeEvent(event)

    def accept(self) -> None:
        self._wait_for_workers()
        super().accept()

    def reject(self) -> None:
        self._wait_for_workers()
        super().reject()

    def _wait_for_workers(self) -> None:
        for worker in (self._contacts_worker, self._action_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)

    def _build_ui(self) -> None:
        self.setWindowTitle("Zusatzrechnung")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        form = QFormLayout()

        form.addRow("Kunde:", QLabel(self._case.customer_name or self._case.customer_email or "—"))
        form.addRow("Wix-Bestellung:", QLabel(self._case.source_wix_order_number or "—"))
        form.addRow("Kulanz:", QLabel("Ja (30 % Produkt, 100 % Versand)" if self._case.courtesy else "Nein"))

        invoiceable = [item for item in self._items if item.role in _INVOICEABLE_ROLES]
        discount = self._pricing.resolve_product_discount(courtesy=self._case.courtesy)
        lines = [f"{item.quantity}x {item.name} ({item.sku})" for item in invoiceable] or ["—"]
        self._positions_view = QPlainTextEdit("\n".join(lines))
        self._positions_view.setReadOnly(True)
        self._positions_view.setMaximumHeight(120)
        form.addRow(f"Positionen (Rabatt {discount.percent:g}%):", self._positions_view)

        self._contact_combo = QComboBox()
        self._contact_combo.setEditable(False)
        form.addRow("sevDesk-Kontakt:", self._contact_combo)

        self._country_edit = QLineEdit("AT")
        self._country_edit.setMaxLength(2)
        self._country_edit.setFixedWidth(60)
        form.addRow("Rechnungsland (ISO2):", self._country_edit)

        self._status = QLabel("")
        form.addRow("", self._status)

        root.addLayout(form)

        buttons = QDialogButtonBox()
        self._btn_create = QPushButton("Zusatzrechnung erstellen")
        self._btn_skip = QPushButton("Ohne Rechnung erledigen")
        self._btn_later = QPushButton("Später")
        buttons.addButton(self._btn_create, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self._btn_skip, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._btn_later, QDialogButtonBox.ButtonRole.RejectRole)
        self._btn_create.clicked.connect(self._on_create_clicked)
        self._btn_skip.clicked.connect(self._on_skip_clicked)
        self._btn_later.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _load_contacts(self) -> None:
        if self._contacts_worker is not None and self._contacts_worker.isRunning():
            return
        self._status.setText("Lade sevDesk-Kontakte…")

        def job() -> list[ContactRecord]:
            return self._contacts_client.list_contacts()

        def on_result(contacts: object) -> None:
            self._contacts = contacts if isinstance(contacts, list) else []
            self._populate_contacts()
            self._status.setText("")

        def on_error(exc: Exception) -> None:
            self._status.setText(f"Kontakte konnten nicht geladen werden: {exc}")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_contacts_worker", None))
        self._contacts_worker = worker
        worker.start()

    def _populate_contacts(self) -> None:
        self._contact_combo.clear()
        wanted_email = (self._case.customer_email or "").strip().casefold()
        preselect = -1
        for index, contact in enumerate(self._contacts):
            label = f"{contact.name} ({contact.email or contact.id})"
            self._contact_combo.addItem(label, contact.id)
            if wanted_email and (contact.email or "").strip().casefold() == wanted_email:
                preselect = index
        if preselect >= 0:
            self._contact_combo.setCurrentIndex(preselect)

    def _selected_contact_id(self) -> str:
        return str(self._contact_combo.currentData() or "")

    def _on_create_clicked(self) -> None:
        contact_id = self._selected_contact_id()
        if not contact_id:
            QMessageBox.warning(self, "Zusatzrechnung", "Bitte einen sevDesk-Kontakt auswählen.")
            return
        country_code = self._country_edit.text().strip().upper()
        if len(country_code) != 2:
            QMessageBox.warning(self, "Zusatzrechnung", "Bitte ein gültiges 2-stelliges Länderkürzel angeben.")
            return
        if self._action_worker is not None and self._action_worker.isRunning():
            return
        self._status.setText("Erstelle Rechnung…")
        self._set_buttons_enabled(False)

        def job() -> InvoiceCreationResult:
            return self._invoices.create_invoice(
                self._case, self._items, contact_id=contact_id, country_code=country_code
            )

        def on_result(result: object) -> None:
            self._set_buttons_enabled(True)
            if isinstance(result, InvoiceCreationResult):
                self.created_invoice = result
                self.action_taken = "invoiced"
                self.accept()

        def on_error(exc: Exception) -> None:
            self._set_buttons_enabled(True)
            self._status.setText(f"Fehler: {exc}")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_action_worker", None))
        self._action_worker = worker
        worker.start()

    def _on_skip_clicked(self) -> None:
        if self._action_worker is not None and self._action_worker.isRunning():
            return
        self._set_buttons_enabled(False)

        def job() -> None:
            self._aftercare.mark_invoice_skipped(self._case.id)

        def on_result(_result: object) -> None:
            self.action_taken = "skipped"
            self.accept()

        def on_error(exc: Exception) -> None:
            self._set_buttons_enabled(True)
            self._status.setText(f"Fehler: {exc}")

        worker = BackgroundWorker(job)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda: setattr(self, "_action_worker", None))
        self._action_worker = worker
        worker.start()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._btn_create.setEnabled(enabled)
        self._btn_skip.setEnabled(enabled)
        self._btn_later.setEnabled(enabled)
