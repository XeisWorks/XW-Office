"""START confirmation dialog for source-aware buyer notes."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from xw_office.services.invoice_processing.buyer_notes import (
    BUYER_NOTE_ACK,
    BUYER_NOTE_DELIVERY_NOTE,
    BUYER_NOTE_DIGITAL_ACK,
    BUYER_NOTE_SKIP,
    BuyerNoteCase,
    BuyerNoteReviewSelection,
    normalized_lines,
)


class BuyerNoteReviewDialog(QDialog):
    """Review every buyer note in the exact START scope before execution."""

    def __init__(
        self,
        cases: list[BuyerNoteCase],
        *,
        allow_delivery_note: bool,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("START – Käufernotizen und Lieferschein")
        self.resize(980, 650)
        self._cases = list(cases)
        self._allow_delivery_note = bool(allow_delivery_note)
        self._selections: dict[str, BuyerNoteReviewSelection] = {}
        self._current_index = -1
        self._build_ui()
        for case in self._cases:
            item = QListWidgetItem(self._item_label(case))
            item.setData(Qt.ItemDataRole.UserRole, case.invoice_id)
            self._case_list.addItem(item)
        if self._cases:
            self._case_list.setCurrentRow(0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        intro = QLabel(
            "Vor START müssen Käufernotizen geprüft werden. Eine markierte Bestellung "
            "kann einen kundenfähigen Lieferschein direkt vor Rechnung und Label drucken."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        split = QHBoxLayout()
        self._case_list = QListWidget()
        self._case_list.setMinimumWidth(300)
        self._case_list.currentRowChanged.connect(self._show_case)
        split.addWidget(self._case_list)

        detail = QVBoxLayout()
        self._headline = QLabel()
        self._headline.setStyleSheet("font-size: 15px; font-weight: bold;")
        detail.addWidget(self._headline)
        self._source = QLabel()
        self._source.setStyleSheet("color: #64748b;")
        detail.addWidget(self._source)
        self._note = QPlainTextEdit()
        self._note.setReadOnly(True)
        self._note.setPlaceholderText("Keine Käufernotiz")
        detail.addWidget(self._note, stretch=2)

        address_box = QGroupBox("Lieferadresse – vor Lieferscheindruck prüfbar")
        address_form = QFormLayout(address_box)
        self._address = QPlainTextEdit()
        self._address.setPlaceholderText("Adresse fehlt – Lieferschein ist dann nicht möglich.")
        self._address.setMaximumHeight(110)
        address_form.addRow(self._address)
        detail.addWidget(address_box)

        self._products = QLabel()
        self._products.setWordWrap(True)
        detail.addWidget(self._products)
        self._manual_note = QPlainTextEdit()
        self._manual_note.setPlaceholderText("Optionaler Zusatz auf dem Lieferschein")
        self._manual_note.setMaximumHeight(75)
        detail.addWidget(self._manual_note)

        actions = QHBoxLayout()
        self._ack = QPushButton("Gelesen – ohne Lieferschein")
        self._ack.clicked.connect(lambda: self._choose(BUYER_NOTE_ACK))
        actions.addWidget(self._ack)
        self._delivery = QPushButton("Lieferschein vormerken")
        self._delivery.clicked.connect(lambda: self._choose(BUYER_NOTE_DELIVERY_NOTE))
        actions.addWidget(self._delivery)
        self._digital = QPushButton("Digital bestätigt")
        self._digital.clicked.connect(lambda: self._choose(BUYER_NOTE_DIGITAL_ACK))
        actions.addWidget(self._digital)
        self._skip = QPushButton("Diesen Datensatz überspringen")
        self._skip.clicked.connect(lambda: self._choose(BUYER_NOTE_SKIP))
        actions.addWidget(self._skip)
        detail.addLayout(actions)
        split.addLayout(detail, stretch=1)
        root.addLayout(split, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        self._continue = buttons.addButton("START fortsetzen", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept_if_complete)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _item_label(case: BuyerNoteCase) -> str:
        ref = f" · Wix {case.order_reference}" if case.order_reference else ""
        return f"{case.invoice_number or case.invoice_id}{ref}"

    def _case(self) -> BuyerNoteCase | None:
        if 0 <= self._current_index < len(self._cases):
            return self._cases[self._current_index]
        return None

    def _save_editor_values(self) -> None:
        case = self._case()
        if case is None:
            return
        current = self._selections.get(case.invoice_id)
        if current is None:
            return
        self._selections[case.invoice_id] = BuyerNoteReviewSelection(
            action=current.action,
            address_lines=normalized_lines(self._address.toPlainText().splitlines()),
            manual_note=self._manual_note.toPlainText().strip(),
        )

    def _show_case(self, index: int) -> None:
        self._save_editor_values()
        self._current_index = index
        case = self._case()
        if case is None:
            return
        self._headline.setText(f"{case.customer_name or 'Unbekannter Kunde'} · {self._item_label(case)}")
        self._source.setText(f"Quelle: {case.source_labels or 'unbekannt'}")
        self._note.setPlainText(case.note_text)
        selection = self._selections.get(case.invoice_id)
        self._address.setPlainText("\n".join(selection.address_lines if selection else case.address_lines))
        self._manual_note.setPlainText(selection.manual_note if selection else "")
        product_lines = [
            f"{product.quantity} × {product.name or product.sku or 'Produkt'}"
            for product in case.products
        ]
        self._products.setText(
            "Positionen: " + (", ".join(product_lines) if product_lines else "nicht aufgelöst")
        )
        is_digital = case.physical_delivery is False
        self._delivery.setEnabled(self._allow_delivery_note and not is_digital)
        self._digital.setEnabled(is_digital)
        self._digital.setToolTip(
            "Nur für digital-only Bestellungen verfügbar."
            if not is_digital
            else "Digitale Lieferung geprüft; es wird kein Papier ausgegeben."
        )
        self._delivery.setToolTip(
            "Bei digital-only Bestellungen gibt es keinen Papier-Lieferschein."
            if is_digital
            else "Adressdaten prüfen; der Lieferschein wird direkt vor der Rechnung gedruckt."
        )

    def _choose(self, action: str) -> None:
        case = self._case()
        if case is None:
            return
        address = normalized_lines(self._address.toPlainText().splitlines())
        if action == BUYER_NOTE_DELIVERY_NOTE and not address:
            QMessageBox.warning(self, "Lieferadresse fehlt", "Für den Lieferschein muss eine Lieferadresse vorhanden sein.")
            return
        self._selections[case.invoice_id] = BuyerNoteReviewSelection(
            action=action,
            address_lines=address,
            manual_note=self._manual_note.toPlainText().strip(),
        )
        item = self._case_list.item(self._current_index)
        if item is not None:
            labels = {
                BUYER_NOTE_ACK: "Gelesen",
                BUYER_NOTE_DELIVERY_NOTE: "Lieferschein",
                BUYER_NOTE_DIGITAL_ACK: "Digital bestätigt",
                BUYER_NOTE_SKIP: "Übersprungen",
            }
            item.setText(f"{self._item_label(case)} · {labels.get(action, action)}")

    def _accept_if_complete(self) -> None:
        self._save_editor_values()
        missing = [case for case in self._cases if case.invoice_id not in self._selections]
        if missing:
            QMessageBox.warning(
                self,
                "Prüfung unvollständig",
                f"Bitte noch {len(missing)} Käufernotiz(en) bestätigen oder überspringen.",
            )
            return
        self.accept()

    def selections(self) -> dict[str, tuple[BuyerNoteCase, BuyerNoteReviewSelection]]:
        return {
            case.invoice_id: (case, self._selections[case.invoice_id])
            for case in self._cases
            if case.invoice_id in self._selections
        }
