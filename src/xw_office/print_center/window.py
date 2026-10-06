"""Small standalone window, intentionally without Office navigation."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, QUrl, Qt
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from xw_office.core.shared_paths import resolve_shared_path
from xw_office.core.worker import BackgroundWorker
from xw_office.print_center.article_dialog import ArticleDialog
from xw_office.print_center.models import PrintArticle, PrintReceipt
from xw_office.print_center.service import PrintCenterService
from xw_office.services.printing.planned_pdf_printer import PrintPlanPartialFailure

logger = logging.getLogger(__name__)


class PrintCenterWindow(QMainWindow):
    def __init__(self, service: PrintCenterService) -> None:
        super().__init__()
        self._service = service
        self._worker: BackgroundWorker | None = None
        self._articles: list[PrintArticle] = []
        self._visible: list[PrintArticle] = []
        self._settings = QSettings("XeisWorks", "Druckcenter")
        saved_favorites = self._settings.value("favorites", [], type=list)
        self._favorites: set[str] = (
            {str(value) for value in saved_favorites}
            if isinstance(saved_favorites, list) else set()
        )
        self.setWindowTitle("XeisWorks Druckcenter")
        self.resize(1050, 720)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.addWidget(QLabel("Drucken nach Bedarf - ohne Bestellung und ohne Bestandsbuchung"))
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "Offizielle Produkte (readonly)")
        self.tabs.addTab(QWidget(), "Eigene Druckartikel")
        self.tabs.currentChanged.connect(self._render)
        root.addWidget(self.tabs)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Name oder SKU suchen")
        self.search.textChanged.connect(self._render)
        search_row.addWidget(self.search)
        self.favorite_only = QCheckBox("Nur Favoriten")
        self.favorite_only.toggled.connect(self._render)
        search_row.addWidget(self.favorite_only)
        self.refresh_button = QPushButton("Neu laden")
        self.refresh_button.clicked.connect(self.reload)
        search_row.addWidget(self.refresh_button)
        root.addLayout(search_row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Favorit", "Name", "SKU", "PDF"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 320)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, stretch=1)
        self.details = QLabel("Bitte einen Druckartikel auswaehlen.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.details)
        actions = QHBoxLayout()
        self.new_button = QPushButton("Artikel anlegen")
        self.edit_button = QPushButton("Bearbeiten")
        self.delete_button = QPushButton("Loeschen")
        self.new_button.clicked.connect(lambda: self._edit_article(new=True))
        self.edit_button.clicked.connect(lambda: self._edit_article(new=False))
        self.delete_button.clicked.connect(self._delete_article)
        self.preview_button = QPushButton("PDF oeffnen")
        self.preview_button.clicked.connect(self._preview)
        self.favorite_button = QPushButton("Favorit umschalten")
        self.favorite_button.clicked.connect(self._toggle_favorite)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setValue(1)
        self.print_button = QPushButton("Drucken")
        self.print_button.clicked.connect(self._print)
        for button in (
            self.new_button, self.edit_button, self.delete_button,
            self.preview_button, self.favorite_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(QLabel("Anzahl:"))
        actions.addWidget(self.copies)
        actions.addWidget(self.print_button)
        root.addLayout(actions)
        self.status = QLabel("Daten werden aus Railway geladen.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._selection_changed()
        self.reload()

    def reload(self) -> None:
        self._run(self._service.list_articles, self._loaded, "Katalog wird geladen ...")

    def _run(
        self, operation: Callable[[], object], on_result: Callable[[object], None], message: str,
    ) -> None:
        if self._worker is not None:
            return
        self.status.setText(message)
        worker = BackgroundWorker(operation)
        self._worker = worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self._error)
        worker.signals.finished.connect(self._finished)
        self.centralWidget().setEnabled(False)
        worker.start()

    def _finished(self) -> None:
        self._worker = None
        self.centralWidget().setEnabled(True)
        self._selection_changed()

    def _error(self, error: Exception) -> None:
        logger.error("Print center operation failed: %s", error)
        message = str(error)
        if isinstance(error, PrintPlanPartialFailure):
            message += (
                f"\nVollstaendig bestaetigte Exemplare: {error.completed_copies}. "
                "Ein weiterer Satz kann teilweise gedruckt sein; bitte vor Wiederholung pruefen."
            )
        elif isinstance(error, TimeoutError):
            message += (
                "\nEin Druckauftrag kann noch laufen. Vor einer Wiederholung bitte "
                "Windows-Druckwarteschlange und Papierausgabe pruefen."
            )
        self.status.setText(f"Fehlgeschlagen: {message}")
        QMessageBox.critical(self, "Druckcenter", message)

    def _loaded(self, result: object) -> None:
        if not isinstance(result, list) or not all(isinstance(a, PrintArticle) for a in result):
            raise TypeError("Ungueltige Katalogantwort.")
        self._articles = result
        self._render()
        self.status.setText(
            f"{sum(a.source == 'official' for a in self._articles)} offizielle Produkte, "
            f"{sum(a.source == 'own' for a in self._articles)} eigene Druckartikel."
        )

    def _render(self) -> None:
        source = "official" if self.tabs.currentIndex() == 0 else "own"
        self.table.setColumnHidden(2, source == "own")
        self.search.setPlaceholderText(
            "Name oder SKU suchen" if source == "official" else "Eigene Druckartikel suchen"
        )
        query = self.search.text().strip().casefold()
        self._visible = [
            a for a in self._articles if a.source == source
            and (not query or query in f"{a.name} {a.sku}".casefold())
            and (not self.favorite_only.isChecked() or a.id in self._favorites)
        ]
        self.table.setRowCount(len(self._visible))
        for index, article in enumerate(self._visible):
            for column, value in enumerate((
                "*" if article.id in self._favorites else "", article.name,
                article.sku, article.pdf_path or "(nicht zugeordnet)",
            )):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.table.clearSelection()
        self._selection_changed()

    def _selected(self) -> PrintArticle | None:
        selection = self.table.selectionModel().selectedRows()
        row = selection[0].row() if selection else -1
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def _selection_changed(self) -> None:
        article = self._selected()
        own_tab = self.tabs.currentIndex() == 1
        self.new_button.setVisible(own_tab)
        self.edit_button.setVisible(own_tab)
        self.delete_button.setVisible(own_tab)
        self.edit_button.setEnabled(article is not None and article.source == "own")
        self.delete_button.setEnabled(article is not None and article.source == "own")
        self.preview_button.setEnabled(article is not None and bool(article.pdf_path))
        self.favorite_button.setEnabled(article is not None)
        self.print_button.setEnabled(
            article is not None and bool(article.pdf_path)
            and bool(article.profile_id or article.print_plan)
        )
        if article is None:
            self.details.setText("Bitte einen Druckartikel auswaehlen.")
            return
        printing = self._service.printing_settings()
        lines = [f"{article.name}\nPDF: {article.pdf_path or '(nicht zugeordnet)'}"]
        steps = article.print_plan
        profile_ids = [(step.range, step.profile_id) for step in steps]
        if not steps and article.profile_id:
            profile_ids = [("Alle Seiten", article.profile_id)]
        for page_range, profile_id in profile_ids:
            profile = printing.resolve_profile(profile_id)
            description = (
                f"{profile.label or profile.id} / {profile.printer_name} / {profile.backend}"
                if profile else f"{profile_id} (Profil nicht verfuegbar)"
            )
            lines.append(f"{page_range}: {description}")
        if not profile_ids:
            lines.append("Kein Druckprofil: bitte in XW-Office zuordnen.")
        if article.notes:
            lines.append(article.notes)
        self.details.setText("\n".join(lines))

    def _edit_article(self, *, new: bool) -> None:
        article = None if new else self._selected()
        if not new and (article is None or article.source != "own"):
            return
        dialog = ArticleDialog(self._service.printing_settings(), article, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.data is None:
            return
        data = dialog.data
        self._run(
            lambda: self._service.save_own(
                data, article_id=article.id if article else None,
                version=article.row_version if article else 1,
            ),
            self._saved, "Artikel wird gespeichert ...",
        )

    def _saved(self, result: object) -> None:
        if not isinstance(result, PrintArticle):
            raise TypeError("Ungueltige Artikelantwort.")
        self._articles = [a for a in self._articles if a.id != result.id] + [result]
        self._render()
        self.status.setText("Eigener Artikel gespeichert. Keine externe Synchronisation.")

    def _delete_article(self) -> None:
        article = self._selected()
        if article is None or article.source != "own":
            return
        if QMessageBox.question(
            self, "Artikel loeschen", f"'{article.name}' wirklich loeschen?\nDie PDF bleibt erhalten."
        ) != QMessageBox.StandardButton.Yes:
            return

        def deleted(_result: object) -> None:
            self._articles = [a for a in self._articles if a.id != article.id]
            self._favorites.discard(article.id)
            self._store_favorites()
            self._render()
            self.status.setText("Eigener Druckartikel geloescht.")

        self._run(
            lambda: self._service.delete_own(article.id, version=article.row_version),
            deleted, "Artikel wird geloescht ...",
        )

    def _preview(self) -> None:
        article = self._selected()
        if article is None:
            return
        path = resolve_shared_path(article.pdf_path)
        if not Path(path).is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.warning(self, "PDF oeffnen", "Die PDF konnte nicht geoeffnet werden.")

    def _store_favorites(self) -> None:
        self._settings.setValue("favorites", sorted(self._favorites))

    def _toggle_favorite(self) -> None:
        article = self._selected()
        if article is None:
            return
        if article.id in self._favorites:
            self._favorites.remove(article.id)
        else:
            self._favorites.add(article.id)
        self._store_favorites()
        self._render()

    def _print(self) -> None:
        article = self._selected()
        if article is None:
            return
        copies = self.copies.value()
        if QMessageBox.question(
            self, "Produktdruck", f"{copies} Exemplar(e) von '{article.name}' drucken?\n"
            "Es erfolgt keine Bestandsbuchung."
        ) != QMessageBox.StandardButton.Yes:
            return
        self._run(
            lambda: self._service.print_article(article, copies),
            self._printed, "Druck laeuft - warte auf Windows-Spooler-Bestaetigung ...",
        )

    def _printed(self, result: object) -> None:
        if not isinstance(result, PrintReceipt):
            raise TypeError("Ungueltige Druckbestaetigung.")
        self.status.setText(
            f"Windows-Spooler hat {result.copies} Exemplar(e) von '{result.name}' bestaetigt."
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None:
            QMessageBox.information(
                self, "Vorgang laeuft", "Bitte den laufenden Vorgang vor dem Schliessen abwarten."
            )
            event.ignore()
            return
        if not self._service.shutdown():
            QMessageBox.information(
                self, "Druckauftrag laeuft",
                "Die Druckpipeline ist noch aktiv. Bitte kurz warten und erneut schliessen.",
            )
            event.ignore()
            return
        super().closeEvent(event)
