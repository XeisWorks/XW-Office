"""Interactive clarification for unpublished-note title aliases and owners."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
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


class UnreleasedProductEditDialog(QDialog):
    """Create or edit an unreleased canonical product with its owner and aliases."""

    def __init__(
        self,
        catalog: ProductCatalogService,
        *,
        canonical_name: str = "",
        owner: str = "",
        aliases: list[str] | tuple[str, ...] = (),
        title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        if title:
            self.setWindowTitle(title)
        else:
            self.setWindowTitle(
                "Unreleased-Produkt bearbeiten" if canonical_name else "Neues Unreleased-Produkt anlegen"
            )
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name_input = QLineEdit(canonical_name)
        self._name_input.setPlaceholderText("z.B. Gabriellas Song XXL")
        self._name_input.textChanged.connect(self._on_name_changed)
        form.addRow("Produktname (Kanonisch):", self._name_input)

        self._owner_combo = QComboBox()
        self._owner_combo.setEditable(True)
        self._owner_combo.addItems(catalog.unreleased_owners())
        if owner:
            self._owner_combo.setCurrentText(owner)
        form.addRow("Gattung / Owner:", self._owner_combo)

        self._aliases_input = QPlainTextEdit()
        self._aliases_input.setPlaceholderText("Ein Alias pro Zeile, z.B.:\nGabriellas Song (XXL Version)\nGabriellas Song XXL")
        cleaned_aliases = [str(a or "").strip() for a in aliases if str(a or "").strip()]
        self._aliases_input.setPlainText("\n".join(cleaned_aliases))
        self._aliases_input.setMaximumHeight(120)
        form.addRow("Aliase (ein Alias pro Zeile):", self._aliases_input)

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

    def _on_name_changed(self, text: str) -> None:
        trimmed = text.strip().casefold()
        if not trimmed:
            return
        for product in self._catalog.list_unreleased_products():
            if product.canonical_name.casefold() == trimmed:
                if product.owners:
                    self._owner_combo.setCurrentText(product.owners[0])
                break

    def _validate_and_accept(self) -> None:
        name = self._name_input.text().strip()
        owner = self._owner_combo.currentText().strip()
        if not name:
            self._error.setText("Bitte einen Produktnamen eingeben.")
            return
        if not owner:
            self._error.setText("Bitte eine Gattung / Owner eingeben oder auswählen.")
            return
        self.accept()

    def get_data(self) -> tuple[str, str, list[str]]:
        raw_aliases = [line.strip() for line in self._aliases_input.toPlainText().splitlines() if line.strip()]
        return (
            self._name_input.text().strip(),
            self._owner_combo.currentText().strip(),
            raw_aliases,
        )


class UnreleasedCatalogDialog(QDialog):
    """Manage all unreleased products (XW-010) and their aliases."""

    def __init__(
        self,
        catalog: ProductCatalogService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self.setWindowTitle("Unreleased-Katalog (XW-010)")
        self.resize(750, 520)

        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        search_label = QLabel("Suchen:")
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter nach Titel, Alias oder Owner...")
        self._search_input.textChanged.connect(self._refresh_list)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self._search_input, stretch=1)
        layout.addLayout(search_layout)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Produktname", "Owner", "Aliase"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.itemDoubleClicked.connect(self._on_edit_clicked)
        layout.addWidget(self._table, stretch=1)

        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("Neu anlegen...")
        self._add_btn.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(self._add_btn)

        self._edit_btn = QPushButton("Bearbeiten...")
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("Löschen")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(self._delete_btn)

        btn_layout.addStretch(1)

        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self._refresh_list()

    def _refresh_list(self) -> None:
        filter_text = self._search_input.text().strip().casefold()
        products = self._catalog.list_unreleased_products()
        filtered = []
        for p in products:
            if not filter_text:
                filtered.append(p)
                continue
            matches = (
                filter_text in p.canonical_name.casefold()
                or any(filter_text in o.casefold() for o in p.owners)
                or any(filter_text in a.casefold() for a in p.aliases)
            )
            if matches:
                filtered.append(p)

        self._displayed_products = filtered
        self._table.setRowCount(len(filtered))
        for row, prod in enumerate(filtered):
            name_item = QTableWidgetItem(prod.canonical_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            owner_item = QTableWidgetItem(", ".join(prod.owners))
            owner_item.setFlags(owner_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            aliases_item = QTableWidgetItem(", ".join(prod.aliases))
            aliases_item.setFlags(aliases_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, owner_item)
            self._table.setItem(row, 2, aliases_item)

    def _selected_product(self) -> object | None:
        row = self._table.currentRow()
        if 0 <= row < len(self._displayed_products):
            return self._displayed_products[row]
        return None

    def _on_add_clicked(self) -> None:
        dialog = UnreleasedProductEditDialog(self._catalog, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, owner, aliases = dialog.get_data()
            self._catalog.add_or_update_unreleased_product(name, owner=owner, aliases=aliases)
            self._refresh_list()

    def _on_edit_clicked(self) -> None:
        prod = self._selected_product()
        if prod is None:
            return
        owner = prod.owners[0] if prod.owners else ""
        dialog = UnreleasedProductEditDialog(
            self._catalog,
            canonical_name=prod.canonical_name,
            owner=owner,
            aliases=list(prod.aliases),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, owner, aliases = dialog.get_data()
            if name != prod.canonical_name:
                self._catalog.delete_unreleased_product(prod.canonical_name)
            self._catalog.add_or_update_unreleased_product(name, owner=owner, aliases=aliases)
            self._refresh_list()

    def _on_delete_clicked(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        prod = self._selected_product()
        if prod is None:
            return
        reply = QMessageBox.question(
            self,
            "Produkt löschen",
            f"Möchten Sie das Unreleased-Produkt '{prod.canonical_name}' wirklich aus den Einstellungen entfernen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._catalog.delete_unreleased_product(prod.canonical_name)
            self._refresh_list()

