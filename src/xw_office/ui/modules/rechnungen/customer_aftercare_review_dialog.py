"""Review-Popup "Lieferkorrektur erkannt" (spec §4) — a compact confirmation dialog.

No network/DB calls happen inside this dialog; it only produces a
:class:`ReviewDialogOutcome` describing what the user chose. The caller is
responsible for applying it via ``CustomerAftercareService.confirm_case``/
``ignore_case`` on a background worker, matching the project's "no network
on the UI thread" rule.

"Bearbeiten" defers the decision — the case stays ``PENDING_REVIEW`` and is
handled later from the Lieferkorrekturen-Manager instead of opening an
inline item editor here; the popup stays intentionally compact per spec §4
("kompakter Bestätigungsdialog").
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
from typing import Literal

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from xw_office.core.config import AppConfig
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.repositories.customer_aftercare import CustomerAftercareItemInput
from xw_office.services.customer_aftercare.service import resolve_case_policy

#: Dropdown options, in spec §4 order (last entry = "Sonstiges / manuell prüfen").
CASE_TYPE_LABELS: dict[str, str] = {
    "B2B_WRONG_DELIVERY": "B2B – XeisWorks falsch geliefert",
    "B2B_MISSING_ITEMS": "B2B – Artikel fehlt",
    "B2C_WRONG_DELIVERY": "B2C – XeisWorks falsch geliefert",
    "B2B_CUSTOMER_ORDER_ERROR": "B2B – Händler hat falsch bestellt",
    "UNKNOWN": "Sonstiges / manuell prüfen",
}

_COURTESY_TOOLTIP = (
    "Aktiv: 30 % Produktrabatt und 100 % Versandrabatt.\n"
    "Deaktiviert: normale Wix-B2B-Rabatte und normale Versandkosten."
)

_ERROR_PARTY_LABELS = {
    "xeisworks": "XeisWorks",
    "customer": "Kunde/Händler",
    "unknown": "unbekannt",
}


@dataclass(frozen=True)
class ReviewDialogOutcome:
    action: Literal["confirm", "defer", "ignore"]
    case_type: str
    courtesy: bool
    note: str
    selected_items: tuple[CustomerAftercareItemInput, ...] = ()


class CustomerAftercareReviewDialog(QDialog):
    """ "Lieferkorrektur erkannt" — spec §4."""

    def __init__(
        self,
        case: CustomerAftercareCase,
        items: list[CustomerAftercareItem],
        *,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lieferkorrektur erkannt")
        self.setMinimumWidth(480)
        self._case = case
        self._items = items
        self._config = config
        self._outcome: ReviewDialogOutcome | None = None
        self._build_ui()

    def outcome(self) -> ReviewDialogOutcome | None:
        return self._outcome

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        wrong_items = [item for item in self._items if item.role == "WRONG_DELIVERED"]
        missing_items = [item for item in self._items if item.role == "MISSING_TO_SEND"]

        form.addRow("Kunde:", QLabel(self._case.customer_name or self._case.customer_email or "—"))
        form.addRow("Wix-Bestellung:", QLabel(self._case.source_wix_order_number or "—"))

        self._type_combo = QComboBox()
        for case_type, label in CASE_TYPE_LABELS.items():
            self._type_combo.addItem(label, case_type)
        initial_type = self._case.case_type or self._case.ai_suggested_type or "UNKNOWN"
        index = self._type_combo.findData(initial_type)
        self._type_combo.setCurrentIndex(
            index if index >= 0 else self._type_combo.findData("UNKNOWN")
        )
        self._type_combo.currentIndexChanged.connect(self._refresh_trigger_preview)
        form.addRow("Falltyp:", self._type_combo)

        form.addRow("Falsch geliefert:", QLabel(self._format_items(wrong_items)))
        form.addRow("Fehlt / nachzusenden:", QLabel(self._format_items(missing_items)))
        form.addRow("Verursacher (KI-Vermutung):", QLabel(self._error_party_label()))

        self._courtesy_checkbox = QCheckBox("Kulanz anwenden")
        self._courtesy_checkbox.setChecked(
            bool(self._case.courtesy)
            if self._case.courtesy is not None
            else self._config.customer_aftercare.courtesy.default_enabled
        )
        self._courtesy_checkbox.setToolTip(_COURTESY_TOOLTIP)
        form.addRow("", self._courtesy_checkbox)

        self._trigger_label = QLabel()
        self._due_label = QLabel()
        form.addRow("Trigger:", self._trigger_label)
        form.addRow("Fälligkeit:", self._due_label)

        self._note_edit = QPlainTextEdit()
        self._note_edit.setPlainText(self._case.note or "")
        self._note_edit.setFixedHeight(60)
        form.addRow("Notiz:", self._note_edit)

        layout.addLayout(form)

        layout.addWidget(QLabel("Nachzuliefernde Rechnungspositionen / Stimmen bestätigen:"))
        self._items_table = QTableWidget(0, 4)
        self._items_table.setHorizontalHeaderLabels(["", "Position", "SKU / Komponente", "Menge"])
        self._items_table.setMaximumHeight(190)
        for item in self._items:
            if item.role == "WRONG_DELIVERED":
                continue
            row = self._items_table.rowCount()
            self._items_table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(
                Qt.CheckState.Unchecked
                if item.role == "ORIGINAL_CANDIDATE"
                else Qt.CheckState.Checked
            )
            check.setData(Qt.ItemDataRole.UserRole, item)
            self._items_table.setItem(row, 0, check)
            name = item.name or item.sku
            if item.parent_sku:
                name = f"{name} (Stimme aus {item.parent_sku})"
            self._items_table.setItem(row, 1, QTableWidgetItem(name))
            self._items_table.setItem(
                row, 2, QTableWidgetItem(" / ".join(filter(None, (item.sku, item.component_id))))
            )
            self._items_table.setItem(
                row, 3, QTableWidgetItem(str(max(1, int(item.quantity or 1))))
            )
        layout.addWidget(self._items_table)

        if self._case.source_mail_body:
            mail = QPlainTextEdit()
            mail.setReadOnly(True)
            mail.setMaximumHeight(110)
            mail.setPlainText(self._case.source_mail_body)
            layout.addWidget(QLabel("Mailtext:"))
            layout.addWidget(mail)

        button_row = QDialogButtonBox()
        self._btn_apply = QPushButton("Übernehmen")
        self._btn_edit = QPushButton("Bearbeiten")
        self._btn_ignore = QPushButton("Ignorieren")
        button_row.addButton(self._btn_apply, QDialogButtonBox.ButtonRole.AcceptRole)
        button_row.addButton(self._btn_edit, QDialogButtonBox.ButtonRole.ActionRole)
        button_row.addButton(self._btn_ignore, QDialogButtonBox.ButtonRole.DestructiveRole)
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_edit.clicked.connect(self._on_defer)
        self._btn_ignore.clicked.connect(self._on_ignore)
        layout.addWidget(button_row)

        self._refresh_trigger_preview()

    @staticmethod
    def _format_items(items: list[CustomerAftercareItem]) -> str:
        if not items:
            return "—"
        lines = []
        for item in items:
            sku = f" ({item.sku})" if item.sku else ""
            lines.append(f"{item.quantity}x {item.name}{sku}")
        return "\n".join(lines)

    def _error_party_label(self) -> str:
        try:
            payload = json.loads(self._case.ai_payload_json or "{}")
        except (TypeError, ValueError):
            return "—"
        party = str(payload.get("error_party") or "").strip()
        return _ERROR_PARTY_LABELS.get(party, "—")

    def _refresh_trigger_preview(self) -> None:
        case_type = str(self._type_combo.currentData())
        policy = resolve_case_policy(case_type)
        if case_type == "UNKNOWN":
            self._trigger_label.setText("Manuell (kein automatischer Trigger)")
            self._due_label.setText("—")
            return
        if policy.wait_for_next_order:
            max_days = self._config.customer_aftercare.b2b.max_wait_days
            due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=max_days)
            self._trigger_label.setText(
                f"Wartet auf neue Bestellung, spätestens nach {max_days} Tagen"
            )
            self._due_label.setText(due.strftime("%d.%m.%Y"))
        else:
            self._trigger_label.setText("Sofort fällig")
            self._due_label.setText("—")

    def _current_outcome(
        self, action: Literal["confirm", "defer", "ignore"]
    ) -> ReviewDialogOutcome:
        selected: list[CustomerAftercareItemInput] = []
        for row in range(self._items_table.rowCount()):
            check = self._items_table.item(row, 0)
            if check is None or check.checkState() != Qt.CheckState.Checked:
                continue
            original = check.data(Qt.ItemDataRole.UserRole)
            if not isinstance(original, CustomerAftercareItem):
                continue
            try:
                quantity = max(1, int(self._items_table.item(row, 3).text()))
            except (AttributeError, ValueError):
                quantity = 1
            quantity = min(quantity, max(1, int(original.quantity or 1)))
            selected.append(
                CustomerAftercareItemInput(
                    role="MISSING_TO_SEND",
                    sku=original.sku,
                    name=original.name,
                    quantity=quantity,
                    sevdesk_part_id=original.sevdesk_part_id,
                    source_unit_price=original.source_unit_price,
                    source_tax_rate=original.source_tax_rate,
                    source_discount_percent=original.source_discount_percent,
                    source_kind=original.source_kind,
                    source_item_id=original.source_item_id,
                    parent_sku=original.parent_sku,
                    component_id=original.component_id,
                    origin_invoice_number=original.origin_invoice_number,
                    origin_order_number=original.origin_order_number,
                    note=original.note or "Nachlieferung – nicht verrechnen",
                )
            )
        return ReviewDialogOutcome(
            action=action,
            case_type=str(self._type_combo.currentData()),
            courtesy=self._courtesy_checkbox.isChecked(),
            note=self._note_edit.toPlainText().strip(),
            selected_items=tuple(selected),
        )

    def _on_apply(self) -> None:
        outcome = self._current_outcome("confirm")
        if self._items_table.rowCount() and not outcome.selected_items:
            QMessageBox.warning(
                self,
                "Nachlieferposition fehlt",
                "Bitte mindestens eine Rechnungsposition oder Stimme auswählen.",
            )
            return
        self._outcome = outcome
        self.accept()

    def _on_defer(self) -> None:
        self._outcome = self._current_outcome("defer")
        self.reject()

    def _on_ignore(self) -> None:
        self._outcome = self._current_outcome("ignore")
        self.reject()
