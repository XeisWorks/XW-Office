"""Interactive clarification for unpublished-note title aliases and owners."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.products.catalog import ProductCatalogService


@dataclass(frozen=True)
class UnreleasedTitleDecision:
    raw_title: str
    canonical_name: str
    owner: str


class UnreleasedTitleDialog(QDialog):
    """Let the user map an unknown Wix title to a work and one genre/owner."""

    def __init__(
        self,
        catalog: ProductCatalogService,
        *,
        raw_title: str,
        context: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._raw_title = str(raw_title or "").strip()
        self.setWindowTitle("Unveröffentlichte Note zuordnen")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Der Titel konnte nicht eindeutig über die gespeicherten Aliase einer Gattung "
            "zugeordnet werden. Bitte den richtigen Produktnamen und die Gattung bestätigen."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        if context:
            context_label = QLabel(context)
            context_label.setWordWrap(True)
            layout.addWidget(context_label)

        form = QFormLayout()
        self._title = QLineEdit(self._raw_title)
        self._title.setReadOnly(bool(self._raw_title))
        form.addRow("Gefundener Titel:", self._title)

        self._canonical = QComboBox()
        self._canonical.setEditable(True)
        products = catalog.list_unreleased_products()
        names = [product.canonical_name for product in products]
        self._canonical.addItems(names)
        candidates = catalog.unreleased_title_candidates(self._raw_title)
        if candidates:
            self._canonical.setCurrentText(candidates[0][0].canonical_name)
        form.addRow("Richtiger Produktname:", self._canonical)

        self._owner = QComboBox()
        self._owner.setEditable(True)
        self._owner.addItems(catalog.unreleased_owners())
        self._canonical.currentTextChanged.connect(
            lambda name: self._select_known_owner(catalog, name)
        )
        self._select_known_owner(catalog, self._canonical.currentText())
        form.addRow("Gattung:", self._owner)
        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #dc2626;")
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_known_owner(self, catalog: ProductCatalogService, canonical_name: str) -> None:
        wanted = str(canonical_name or "").strip().casefold()
        for product in catalog.list_unreleased_products():
            if product.canonical_name.casefold() == wanted and len(product.owners) == 1:
                self._owner.setCurrentText(product.owners[0])
                return

    def _validate_and_accept(self) -> None:
        if not self._title.text().strip():
            self._error.setText("Der gefundene Titel darf nicht leer sein.")
            return
        if not self._canonical.currentText().strip():
            self._error.setText("Bitte einen Produktnamen eingeben oder auswählen.")
            return
        if not self._owner.currentText().strip():
            self._error.setText("Bitte eine Gattung eingeben oder auswählen.")
            return
        self.accept()

    def decision(self) -> UnreleasedTitleDecision | None:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return UnreleasedTitleDecision(
            raw_title=self._title.text().strip(),
            canonical_name=self._canonical.currentText().strip(),
            owner=self._owner.currentText().strip(),
        )


class UnreleasedTitleSplitDialog(QDialog):
    """Require exactly one title line for every ordered unpublished piece."""

    def __init__(
        self,
        *,
        quantity: int,
        initial_text: str,
        context: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._quantity = max(1, int(quantity))
        self.setWindowTitle("Stücktitel aufteilen")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        info = QLabel(
            f"Für diese Position werden genau {self._quantity} Stücktitel benötigt. "
            "Bitte jeden Titel in eine eigene Zeile schreiben."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        if context:
            label = QLabel(context)
            label.setWordWrap(True)
            layout.addWidget(label)
        self._titles = QPlainTextEdit()
        self._titles.setPlainText(initial_text)
        layout.addWidget(self._titles)
        self._error = QLabel("")
        self._error.setStyleSheet("color: #dc2626;")
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _values(self) -> list[str]:
        return [line.strip() for line in self._titles.toPlainText().splitlines() if line.strip()]

    def _validate_and_accept(self) -> None:
        values = self._values()
        if len(values) != self._quantity:
            self._error.setText(
                f"Bitte genau {self._quantity} Titel eingeben (aktuell: {len(values)})."
            )
            return
        self.accept()

    def titles(self) -> list[str] | None:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._values()
