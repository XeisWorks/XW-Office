"""Editor for own articles only; central print profiles cannot be edited."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QVBoxLayout, QWidget,
)
from pydantic import ValidationError

from xw_office.core.config import PrintingSection
from xw_office.print_center.models import ArticleInput, PrintArticle, PrintStep


class ArticleDialog(QDialog):
    def __init__(
        self, printing: PrintingSection, article: PrintArticle | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if article is not None and article.source != "own":
            raise ValueError("Offizielle Produkte koennen hier nicht bearbeitet werden.")
        self.setWindowTitle("Eigener Druckartikel")
        self.resize(680, 440)
        self.data: ArticleInput | None = None
        self._profiles = [p for p in printing.all_profiles() if p.backend == "pdf_xchange"]
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(article.name if article else "")
        self.path_edit = QLineEdit(article.pdf_path if article else "")
        self.notes_edit = QLineEdit(article.notes if article else "")
        form.addRow("Name:", self.name_edit)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        browse = QPushButton("PDF waehlen")
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        form.addRow("PDF:", path_row)
        form.addRow("Notiz:", self.notes_edit)
        root.addLayout(form)
        hint = QLabel(
            "Ohne SKU, ohne Wix/sevDesk-Synchronisation und ohne Bestandsbuchung.\n"
            "Profile werden in XW-Office gepflegt. Hier wird nur die Zuordnung gespeichert.\n"
            "Die PDF muss zum Drucken auf diesem PC erreichbar sein."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.plan_table = QTableWidget(0, 2)
        self.plan_table.setHorizontalHeaderLabels(["Seitenbereich", "Druckprofil"])
        self.plan_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.plan_table)
        row = QHBoxLayout()
        add = QPushButton("Druckschritt hinzufuegen")
        add.clicked.connect(lambda: self._add_step())
        remove = QPushButton("Druckschritt entfernen")
        remove.clicked.connect(self._remove_step)
        row.addWidget(add)
        row.addWidget(remove)
        root.addLayout(row)
        for step in article.print_plan if article else ():
            self._add_step(step)
        if not self.plan_table.rowCount():
            self._add_step()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Produkt-PDF", "", "PDF (*.pdf)")
        if path:
            self.path_edit.setText(path)

    def _add_step(self, step: PrintStep | None = None) -> None:
        row = self.plan_table.rowCount()
        self.plan_table.insertRow(row)
        range_edit = QLineEdit(step.range if step else "Alle Seiten")
        self.plan_table.setCellWidget(row, 0, range_edit)
        combo = QComboBox()
        for profile in self._profiles:
            combo.addItem(
                f"{profile.label or profile.id} - {profile.printer_name}", profile.id
            )
        if step:
            index = combo.findData(step.profile_id)
            if index < 0:
                combo.addItem(f"Nicht mehr verfuegbar: {step.profile_id}", step.profile_id)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
        self.plan_table.setCellWidget(row, 1, combo)

    def _remove_step(self) -> None:
        row = self.plan_table.currentRow()
        if row >= 0:
            self.plan_table.removeRow(row)

    def _save(self) -> None:
        try:
            steps: list[PrintStep] = []
            for row in range(self.plan_table.rowCount()):
                range_edit = self.plan_table.cellWidget(row, 0)
                combo = self.plan_table.cellWidget(row, 1)
                if not isinstance(range_edit, QLineEdit) or not isinstance(combo, QComboBox):
                    raise ValueError("Ungueltiger Druckschritt.")
                steps.append(PrintStep(
                    range=range_edit.text() or "Alle Seiten",
                    profile_id=str(combo.currentData() or ""),
                ))
            self.data = ArticleInput(
                name=self.name_edit.text(), pdf_path=self.path_edit.text(),
                notes=self.notes_edit.text(), print_plan=tuple(steps),
            )
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Artikel unvollstaendig", str(exc))
            return
        self.accept()
