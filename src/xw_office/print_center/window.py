"""Small standalone window, intentionally without Office navigation."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QSettings, QSize, QUrl, Qt
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QToolButton, QStyle, QVBoxLayout, QWidget,
)

from xw_office.core.shared_paths import resolve_shared_path
from xw_office.core.worker import BackgroundWorker
from xw_office.print_center.article_dialog import ArticleDialog
from xw_office.print_center.details_dialog import PrintDetailsDialog
from xw_office.print_center.icons import printer_icon
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
        self.resize(1200, 720)
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
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["★", "Name", "SKU", "PDF", "Aktionen"])
        favorite_header = QTableWidgetItem("★")
        favorite_header.setToolTip("Favoriten")
        self.table.setHorizontalHeaderItem(0, favorite_header)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(4, 260)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, stretch=1)
        actions = QHBoxLayout()
        self.new_button = QPushButton("Artikel anlegen")
        self.edit_button = QPushButton("Bearbeiten")
        self.delete_button = QPushButton("Loeschen")
        self.new_button.clicked.connect(lambda: self._edit_article(new=True))
        self.edit_button.clicked.connect(lambda: self._edit_article(new=False))
        self.delete_button.clicked.connect(self._delete_article)
        for button in (
            self.new_button, self.edit_button, self.delete_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
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
                "", article.name, article.sku,
                PureWindowsPath(article.pdf_path).name if article.pdf_path else "(nicht zugeordnet)",
            )):
                self.table.setItem(index, column, QTableWidgetItem(value))
            self.table.setCellWidget(index, 0, self._favorite_control(article))
            self.table.setCellWidget(index, 4, self._row_actions(article))
        self.table.clearSelection()
        self._selection_changed()

    def _favorite_control(self, article: PrintArticle) -> QToolButton:
        button = QToolButton()
        button.setObjectName("article_favorite")
        button.setText("★" if article.id in self._favorites else "☆")
        button.setToolTip("Favorit entfernen" if article.id in self._favorites else "Als Favorit merken")
        button.setAccessibleName(button.toolTip())
        button.setStyleSheet(
            "QToolButton { font-size: 22px; color: #e2b640; padding: 0px; "
            "margin: 0px; border: none; min-width: 0px; }"
        )
        button.clicked.connect(lambda: self._toggle_favorite(article))
        return button

    def _row_actions(self, article: PrintArticle) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(5)
        preview = QToolButton()
        preview.setObjectName("article_pdf")
        preview.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        preview.setIconSize(QSize(20, 20))
        preview.setToolTip("PDF oeffnen")
        preview.setAccessibleName(preview.toolTip())
        preview.setEnabled(bool(article.pdf_path))
        preview.clicked.connect(lambda: self._preview(article))
        layout.addWidget(preview)
        details = QToolButton()
        details.setObjectName("article_details")
        details.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        details.setIconSize(QSize(20, 20))
        details.setToolTip("Druckpfad und Druckeinstellungen anzeigen")
        details.setAccessibleName(details.toolTip())
        details.clicked.connect(lambda: self._show_print_details(article))
        layout.addWidget(details)
        copies = QSpinBox()
        copies.setObjectName("article_copies")
        copies.setRange(1, 999)
        copies.setValue(1)
        copies.setFixedWidth(76)
        copies.setToolTip("Anzahl Exemplare")
        copies.setAccessibleName(copies.toolTip())
        layout.addWidget(copies)
        print_button = QToolButton()
        print_button.setObjectName("article_print")
        print_button.setIcon(printer_icon())
        print_button.setIconSize(QSize(24, 24))
        print_button.setToolTip("Mit hinterlegten Einstellungen drucken")
        print_button.setAccessibleName(print_button.toolTip())
        print_button.setEnabled(bool(article.pdf_path and (article.profile_id or article.print_plan)))
        print_button.clicked.connect(lambda: self._print(article, copies.value()))
        layout.addWidget(print_button)
        return widget

    def _show_print_details(self, article: PrintArticle) -> None:
        dialog = PrintDetailsDialog(article, self._service.printing_settings(), self)
        dialog.exec()
        if dialog.edit_requested:
            self._edit_article(new=False, article=article)

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

    def _edit_article(self, *, new: bool, article: PrintArticle | None = None) -> None:
        article = None if new else article or self._selected()
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

    def _preview(self, article: PrintArticle) -> None:
        path = resolve_shared_path(article.pdf_path)
        if not Path(path).is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.warning(self, "PDF oeffnen", "Die PDF konnte nicht geoeffnet werden.")

    def _store_favorites(self) -> None:
        self._settings.setValue("favorites", sorted(self._favorites))

    def _toggle_favorite(self, article: PrintArticle) -> None:
        if article.id in self._favorites:
            self._favorites.remove(article.id)
        else:
            self._favorites.add(article.id)
        self._store_favorites()
        self._render()

    def _print(self, article: PrintArticle, copies: int) -> None:
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
