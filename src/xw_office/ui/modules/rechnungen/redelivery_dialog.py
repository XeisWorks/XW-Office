"""Editable invoice-driven Nachlieferung dialog."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.repositories.customer_aftercare import CustomerAftercareItemInput


@dataclass(frozen=True)
class RedeliveryDialogOutcome:
    action: Literal["save", "cancel"]
    shipping_mode: str
    address_lines: tuple[str, ...]
    note: str
    items: tuple[CustomerAftercareItemInput, ...]


class RedeliveryDialog(QDialog):
    """Popup for selecting invoice products and activating a redelivery case."""

    def __init__(
        self,
        case: CustomerAftercareCase,
        items: list[CustomerAftercareItem],
        *,
        address_lines: list[str] | tuple[str, ...] = (),
        address_source: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nachlieferung erstellen")
        self.setMinimumSize(820, 680)
        self._case = case
        self._items = list(items)
        self._address_source = str(address_source or "").strip()
        self._outcome: RedeliveryDialogOutcome | None = None
        self._build_ui(address_lines)

    def outcome(self) -> RedeliveryDialogOutcome | None:
        return self._outcome

    def _build_ui(self, address_lines: list[str] | tuple[str, ...]) -> None:
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                f"Rechnung: {self._case.source_invoice_number or '-'}  |  "
                f"Wix-Order: {self._case.source_wix_order_number or '-'}  |  "
                f"Kunde: {self._case.customer_name or self._case.customer_email or '-'}"
            )
        )

        form = QFormLayout()
        self._mode = QComboBox()
        self._mode.addItem("Auf nächste Bestellung warten (max. 20 Tage)", "WAIT_NEXT_ORDER_OR_DEADLINE")
        self._mode.addItem("Sofort separat versenden", "IMMEDIATE")
        current = str(self._case.shipping_mode or "WAIT_NEXT_ORDER_OR_DEADLINE").strip()
        index = self._mode.findData(current)
        self._mode.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Versandmodus:", self._mode)

        self._address = QPlainTextEdit()
        self._address.setPlaceholderText("Name\nStraße\nPLZ Ort\nLand")
        self._address.setPlainText("\n".join(address_lines) or self._decode_address(self._case))
        self._address.setFixedHeight(100)
        form.addRow(f"Lieferadresse ({self._address_source or 'manuell'}):", self._address)

        self._note = QPlainTextEdit()
        self._note.setPlainText(self._case.note or "")
        self._note.setFixedHeight(90)
        form.addRow("Lieferschein-Notiz:", self._note)
        root.addLayout(form)

        root.addWidget(QLabel("Nachzuliefernde Produkte / Product-Hub-Komponenten:"))
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["", "Produkt", "SKU / Komponente", "Menge"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, stretch=1)
        for item in self._items:
            self._add_item_row(item, checked=True)

        add_button = QPushButton("Manuelle Position hinzufügen")
        add_button.clicked.connect(self._add_manual_item)
        root.addWidget(add_button)

        preview_button = QPushButton("Lieferschein-Vorschau")
        preview_button.clicked.connect(self._preview)
        root.addWidget(preview_button)

        buttons = QDialogButtonBox()
        save = QPushButton("Nachlieferung speichern")
        cancel = QPushButton("Abbrechen")
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _preview(self) -> None:
        products: list[str] = []
        for row in range(self._table.rowCount()):
            check = self._table.item(row, 0)
            if check is None or check.checkState() != Qt.CheckState.Checked:
                continue
            name = (self._table.item(row, 1).text() if self._table.item(row, 1) else "Position").strip()
            sku = (self._table.item(row, 2).text() if self._table.item(row, 2) else "").strip()
            qty = (self._table.item(row, 3).text() if self._table.item(row, 3) else "1").strip()
            products.append(f"{qty}x {name}" + (f" ({sku})" if sku else ""))
        address = self._address.toPlainText().strip() or "(Lieferadresse fehlt)"
        note = self._note.toPlainText().strip() or "Kostenlose Nachlieferung – nicht verrechnen."
        QMessageBox.information(
            self,
            "Lieferschein-Vorschau",
            "NACHLIEFERUNG\n\n"
            f"{address}\n\n"
            + ("\n".join(products) if products else "(keine Position ausgewählt)")
            + f"\n\n{note}",
        )

    @staticmethod
    def _decode_address(case: CustomerAftercareCase) -> str:
        import json

        try:
            value = json.loads(case.address_lines_json or "[]")
        except (TypeError, ValueError):
            return ""
        return "\n".join(str(item).strip() for item in value if str(item).strip()) if isinstance(value, list) else ""

    def _add_item_row(self, item: CustomerAftercareItem, *, checked: bool) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        check.setData(Qt.ItemDataRole.UserRole, item)
        self._table.setItem(row, 0, check)
        self._table.setItem(row, 1, QTableWidgetItem(item.name or item.sku or "Position"))
        self._table.setItem(row, 2, QTableWidgetItem(" / ".join(part for part in (item.sku, item.component_id) if part)))
        self._table.setItem(row, 3, QTableWidgetItem(str(max(1, int(item.quantity or 1)))))

    def _add_manual_item(self) -> None:
        name, ok = QInputDialog.getText(self, "Manuelle Position", "Produktbezeichnung:")
        if not ok or not name.strip():
            return
        sku, ok = QInputDialog.getText(self, "Manuelle Position", "SKU (optional):")
        if not ok:
            return
        quantity, ok = QInputDialog.getInt(self, "Manuelle Position", "Menge:", 1, 1, 999)
        if not ok:
            return
        item = CustomerAftercareItem(
            id=uuid.uuid4(),
            case_id=self._case.id,
            role="MISSING_TO_SEND",
            name=name.strip(),
            sku=sku.strip(),
            quantity=quantity,
            source_kind="manual",
            note="Manuelle Nachlieferposition",
        )
        self._add_item_row(item, checked=True)

    def _save(self) -> None:
        selected: list[CustomerAftercareItemInput] = []
        for row in range(self._table.rowCount()):
            check = self._table.item(row, 0)
            if check is None or check.checkState() != Qt.CheckState.Checked:
                continue
            original = check.data(Qt.ItemDataRole.UserRole)
            original = original if isinstance(original, CustomerAftercareItem) else None
            name = (self._table.item(row, 1).text() if self._table.item(row, 1) else "").strip()
            sku = (self._table.item(row, 2).text() if self._table.item(row, 2) else "").strip()
            sku = sku.split(" / ", 1)[0].strip()
            try:
                quantity = max(1, int((self._table.item(row, 3).text() if self._table.item(row, 3) else "1").strip()))
            except ValueError:
                quantity = 1
            if isinstance(original, CustomerAftercareItem) and str(original.source_kind or "") != "manual":
                quantity = min(quantity, max(1, int(original.quantity or 1)))
            selected.append(
                CustomerAftercareItemInput(
                    role="MISSING_TO_SEND",
                    name=name,
                    sku=sku,
                    quantity=quantity,
                    sevdesk_part_id=str(getattr(original, "sevdesk_part_id", "") or ""),
                    source_unit_price=getattr(original, "source_unit_price", None),
                    source_tax_rate=getattr(original, "source_tax_rate", None),
                    source_discount_percent=getattr(original, "source_discount_percent", None),
                    source_kind=str(getattr(original, "source_kind", "manual") or "manual"),
                    source_item_id=str(getattr(original, "source_item_id", "") or ""),
                    parent_sku=str(getattr(original, "parent_sku", "") or ""),
                    component_id=str(getattr(original, "component_id", "") or ""),
                    origin_invoice_number=str(getattr(original, "origin_invoice_number", "") or self._case.source_invoice_number),
                    origin_order_number=str(getattr(original, "origin_order_number", "") or self._case.source_wix_order_number),
                    note=str(getattr(original, "note", "") or "Nachlieferung – nicht verrechnen"),
                )
            )
        if not selected:
            self._table.setFocus()
            return
        address = tuple(line.strip() for line in self._address.toPlainText().splitlines() if line.strip())
        self._outcome = RedeliveryDialogOutcome(
            action="save",
            shipping_mode=str(self._mode.currentData() or "WAIT_NEXT_ORDER_OR_DEADLINE"),
            address_lines=address,
            note=self._note.toPlainText().strip(),
            items=tuple(selected),
        )
        self.accept()
