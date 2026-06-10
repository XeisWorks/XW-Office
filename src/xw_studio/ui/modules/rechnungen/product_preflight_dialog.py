"""Dialog for missing sevDesk products in Rechnungen START / Draft flows."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_studio.services.draft_invoice.service import ProductDraft, ProductIssue, ProductIssueDecision


class ProductPreflightDialog(QDialog):
    """Prompt for one missing sevDesk product before continuing the flow."""

    def __init__(
        self,
        issue: ProductIssue,
        *,
        part_categories: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._issue = issue
        self._part_categories = [entry for entry in part_categories if str(entry.get("name") or "").strip()]
        self._category_ids_by_name = {
            str(entry.get("name") or "").strip(): str(entry.get("id") or "").strip()
            for entry in self._part_categories
        }
        self._result: ProductIssueDecision | None = None
        self.setWindowTitle(f"Produkt fehlt in sevDesk | {issue.sku}")
        self.setMinimumSize(980, 640)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(
            f"<b>Produkt fehlt in sevDesk</b><br>"
            f"SKU: {self._issue.sku}"
            + (f" | Wix-Order: {self._issue.wix_order_number}" if self._issue.wix_order_number else " | manuelle Produktanlage")
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, stretch=1)

        wix_box = QGroupBox("Wix-Daten")
        wix_layout = QVBoxLayout(wix_box)
        wix_layout.setSpacing(8)
        wix_summary = QLabel(
            "\n".join(
                [
                    f"Name: {self._issue.wix_name or '-'}",
                    f"SKU: {self._issue.sku or '-'}",
                    f"Preis brutto: {self._fmt_num(self._issue.wix_price_gross) or '-'}",
                    f"Digital: {'ja' if self._issue.is_digital else 'nein'}",
                ]
            )
        )
        wix_summary.setWordWrap(True)
        wix_layout.addWidget(wix_summary)
        self._wix_description = QPlainTextEdit()
        self._wix_description.setReadOnly(True)
        self._wix_description.setPlainText(self._issue.wix_description or "-")
        wix_layout.addWidget(QLabel("Wix-Beschreibung"))
        wix_layout.addWidget(self._wix_description, stretch=1)
        self._targets = QPlainTextEdit()
        self._targets.setReadOnly(True)
        target_lines = [
            f"{target.invoice_number or '(neu)'} | {target.wix_order_number or '-'} | {target.customer_name or '-'}"
            for target in self._issue.targets
        ]
        self._targets.setPlainText("\n".join(target_lines) or "Keine Rechnungen verknuepft (manuelle Produktanlage).")
        wix_layout.addWidget(QLabel("Betroffene Rechnungen"))
        wix_layout.addWidget(self._targets, stretch=1)
        body.addWidget(wix_box, stretch=1)

        sev_box = QGroupBox("sevDesk-Entwurf")
        sev_layout = QGridLayout(sev_box)
        sev_layout.setHorizontalSpacing(10)
        sev_layout.setVerticalSpacing(8)

        draft = self._issue.draft
        self._name = QLineEdit(draft.name)
        self._sku = QLineEdit(draft.sku)
        self._price = QLineEdit(self._fmt_num(draft.price_gross))
        self._tax = QLineEdit(self._fmt_num(draft.tax_rate))
        self._category = QComboBox()
        self._category.setEditable(False)
        self._category.addItem("")
        for entry in self._part_categories:
            self._category.addItem(str(entry.get("name") or "").strip())
        if draft.category_name:
            index = self._category.findText(draft.category_name)
            if index >= 0:
                self._category.setCurrentIndex(index)
        self._description = QPlainTextEdit()
        self._description.setPlainText(draft.text)
        self._internal = QPlainTextEdit()
        self._internal.setPlainText(draft.internal_comment)

        sev_layout.addWidget(QLabel("Name"), 0, 0)
        sev_layout.addWidget(self._name, 0, 1)
        sev_layout.addWidget(QLabel("SKU"), 1, 0)
        sev_layout.addWidget(self._sku, 1, 1)
        sev_layout.addWidget(QLabel("Preis brutto"), 2, 0)
        sev_layout.addWidget(self._price, 2, 1)
        sev_layout.addWidget(QLabel("Steuersatz"), 3, 0)
        sev_layout.addWidget(self._tax, 3, 1)
        sev_layout.addWidget(QLabel("Produktkategorie"), 4, 0)
        sev_layout.addWidget(self._category, 4, 1)
        sev_layout.addWidget(QLabel("Beschreibung"), 5, 0)
        sev_layout.addWidget(self._description, 5, 1)
        sev_layout.addWidget(QLabel("Interne Notiz"), 6, 0)
        sev_layout.addWidget(self._internal, 6, 1)
        sev_layout.setRowStretch(5, 1)
        sev_layout.setRowStretch(6, 1)
        body.addWidget(sev_box, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_skip = QPushButton("Überspringen")
        btn_skip.clicked.connect(self._skip)
        btn_create = QPushButton("Produkt anlegen")
        btn_create.clicked.connect(self._create)
        buttons.addWidget(btn_skip)
        buttons.addWidget(btn_create)
        layout.addLayout(buttons)

    def show_dialog(self) -> ProductIssueDecision | None:
        self.exec()
        return self._result

    def _collect_draft(self) -> ProductDraft | None:
        name = self._name.text().strip()
        sku = self._sku.text().strip().upper()
        if not name or not sku:
            QMessageBox.warning(self, "Produkt", "Name und SKU dürfen nicht leer sein.")
            return None
        try:
            price = self._parse_optional_float(self._price.text())
            tax = self._parse_optional_float(self._tax.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Produkt", str(exc))
            return None
        category_name = self._category.currentText().strip()
        return ProductDraft(
            name=name,
            sku=sku,
            text=self._description.toPlainText().strip(),
            internal_comment=self._internal.toPlainText().strip(),
            price_gross=price,
            tax_rate=tax,
            unity={"id": 1, "objectName": "Unity"},
            category_id=self._category_ids_by_name.get(category_name, ""),
            category_name=category_name,
        )

    def _create(self) -> None:
        draft = self._collect_draft()
        if draft is None:
            return
        self._result = ProductIssueDecision(action="create_part", draft=draft)
        self.accept()

    def _skip(self) -> None:
        self._result = ProductIssueDecision(action="skip", draft=self._issue.draft)
        self.reject()

    @staticmethod
    def _fmt_num(value: float | None) -> str:
        if value is None:
            return ""
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _parse_optional_float(value: str) -> float | None:
        text = str(value or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"Ungültige Zahl: {value}") from exc
