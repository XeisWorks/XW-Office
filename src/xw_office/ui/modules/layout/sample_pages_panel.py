"""UI panel: export selected PDF pages as web-optimized JPG sample pages."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.layout.sample_pages_models import (
    DEFAULT_MAX_SIZE_KB,
    DEFAULT_TARGET_HEIGHT_PX,
    SamplePageExportError,
    SamplePageExportResult,
    SamplePageExportSettings,
    SamplePageJob,
    parse_page_numbers,
)
from xw_office.services.layout.sample_pages_service import SamplePageExportService

if TYPE_CHECKING:
    from xw_office.repositories.settings_kv import SettingKvRepository

_OUTPUT_FOLDER_SETTING_KEY = "layout.sample_pages.output_folder"
_COL_PDF = 0
_COL_PAGES = 1
_COL_STATUS = 2


def _default_output_folder() -> str:
    return str(Path.home() / "XeisWorks_Beispielseiten")


class SamplePagesPanel(QWidget):
    """Pick PDFs + page numbers, export each page as a web-optimized JPG."""

    def __init__(
        self,
        service: SamplePageExportService,
        settings_repo: SettingKvRepository | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._settings_repo = settings_repo
        self._worker: BackgroundWorker | None = None
        self._last_output_folder = ""

        root = QVBoxLayout(self)
        intro = QLabel(
            "Wählt aus einer oder mehreren PDFs bestimmte Seiten aus (z. B. 1,5,7 oder 8-12) und "
            "exportiert jede als webkomprimiertes JPG in den Ausgabeordner."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        file_row = QHBoxLayout()
        add_button = QPushButton("PDF(s) hinzufügen…")
        add_button.clicked.connect(self._add_pdfs)
        file_row.addWidget(add_button)
        remove_button = QPushButton("Ausgewählte entfernen")
        remove_button.clicked.connect(self._remove_selected)
        file_row.addWidget(remove_button)
        file_row.addStretch()
        root.addLayout(file_row)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["PDF-Datei", "Seiten (z. B. 1,5,7 oder 8-12)", "Status"])
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_PDF, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_PAGES, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(180)
        root.addWidget(self._table, stretch=1)

        settings_group = QGroupBox("Einstellungen")
        settings_layout = QVBoxLayout(settings_group)

        folder_row = QHBoxLayout()
        self._output_folder_edit = QLineEdit(self._load_output_folder())
        folder_row.addWidget(QLabel("Ausgabeordner:"))
        folder_row.addWidget(self._output_folder_edit, stretch=1)
        browse_button = QPushButton("Ordner wählen…")
        browse_button.clicked.connect(self._pick_output_folder)
        folder_row.addWidget(browse_button)
        settings_layout.addLayout(folder_row)

        numbers_row = QHBoxLayout()
        numbers_row.addWidget(QLabel("Zielhöhe (px):"))
        self._height_spin = QSpinBox()
        self._height_spin.setRange(100, 6000)
        self._height_spin.setValue(DEFAULT_TARGET_HEIGHT_PX)
        numbers_row.addWidget(self._height_spin)
        numbers_row.addWidget(QLabel("Max. Dateigröße (KB):"))
        self._max_size_spin = QSpinBox()
        self._max_size_spin.setRange(10, 10000)
        self._max_size_spin.setValue(DEFAULT_MAX_SIZE_KB)
        numbers_row.addWidget(self._max_size_spin)
        numbers_row.addStretch()
        settings_layout.addLayout(numbers_row)
        root.addWidget(settings_group)

        action_row = QHBoxLayout()
        self._generate_button = QPushButton("Beispielseiten erzeugen")
        self._generate_button.clicked.connect(self._start_export)
        action_row.addWidget(self._generate_button)
        self._open_folder_button = QPushButton("Ausgabeordner öffnen")
        self._open_folder_button.setEnabled(False)
        self._open_folder_button.clicked.connect(self._open_output_folder)
        action_row.addWidget(self._open_folder_button)
        action_row.addStretch()
        root.addLayout(action_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        self._status_label = QLabel("Bereit.")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

    # ------------------------------------------------------------------
    # Output folder persistence
    # ------------------------------------------------------------------

    def _load_output_folder(self) -> str:
        if self._settings_repo is not None:
            value = self._settings_repo.get_value_json(_OUTPUT_FOLDER_SETTING_KEY)
            if value:
                return value
        return _default_output_folder()

    def _save_output_folder(self, value: str) -> None:
        if self._settings_repo is not None:
            self._settings_repo.set_value_json(_OUTPUT_FOLDER_SETTING_KEY, value)

    def _pick_output_folder(self) -> None:
        start = self._output_folder_edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", start)
        if selected:
            self._output_folder_edit.setText(selected)
            self._save_output_folder(selected)

    # ------------------------------------------------------------------
    # PDF table
    # ------------------------------------------------------------------

    def _add_pdfs(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "PDF-Dateien wählen", "", "PDF-Dateien (*.pdf)")
        self._add_pdf_paths(paths)

    def _add_pdf_paths(self, paths: list[str]) -> None:
        for path in paths:
            row = self._table.rowCount()
            self._table.insertRow(row)
            pdf_item = QTableWidgetItem(Path(path).name)
            pdf_item.setFlags(pdf_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            pdf_item.setData(Qt.ItemDataRole.UserRole, path)
            pdf_item.setToolTip(path)
            self._table.setItem(row, _COL_PDF, pdf_item)
            self._table.setItem(row, _COL_PAGES, QTableWidgetItem(""))
            self._table.setItem(row, _COL_STATUS, QTableWidgetItem(""))

    def _remove_selected(self) -> None:
        for row in sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True):
            self._table.removeRow(row)

    def _collect_jobs(self) -> list[SamplePageJob]:
        import fitz  # type: ignore[import-untyped]

        jobs: list[SamplePageJob] = []
        for row in range(self._table.rowCount()):
            pdf_item = self._table.item(row, _COL_PDF)
            pages_item = self._table.item(row, _COL_PAGES)
            status_item = self._table.item(row, _COL_STATUS)
            raw_path = str(pdf_item.data(Qt.ItemDataRole.UserRole) or "") if pdf_item else ""
            pdf_path = Path(raw_path)
            pages_text = pages_item.text() if pages_item else ""
            if not raw_path or not pages_text.strip():
                if status_item:
                    status_item.setText("Übersprungen: keine Seitenangabe.")
                continue
            try:
                with fitz.open(pdf_path) as doc:
                    page_count = doc.page_count
                pages = parse_page_numbers(pages_text, page_count=page_count)
            except Exception as exc:  # noqa: BLE001 - surfaced per row, then re-raised with file context
                if status_item:
                    status_item.setText(f"Fehler: {exc}")
                raise SamplePageExportError(f'"{pdf_path.name}": {exc}') from exc
            jobs.append(SamplePageJob(pdf_path=pdf_path, pages=pages))
            if status_item:
                status_item.setText("Bereit.")
        return jobs

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _start_export(self) -> None:
        try:
            jobs = self._collect_jobs()
        except SamplePageExportError as exc:
            QMessageBox.warning(self, "Eingabe prüfen", str(exc))
            return
        if not jobs:
            QMessageBox.information(self, "Keine Auswahl", "Bitte mindestens eine PDF mit Seitenangabe hinzufügen.")
            return

        output_folder = self._output_folder_edit.text().strip() or _default_output_folder()
        self._save_output_folder(output_folder)
        settings = SamplePageExportSettings(
            output_folder=Path(output_folder),
            target_height_px=self._height_spin.value(),
            max_size_kb=self._max_size_spin.value(),
        )

        worker: BackgroundWorker

        def job() -> list[SamplePageExportResult]:
            return self._service.export(
                jobs,
                settings,
                progress=lambda percent, message: worker.signals.progress.emit(percent, message),
            )

        worker = BackgroundWorker(job)
        self._worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(lambda results: self._on_result(results, output_folder))
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(self._on_finished)
        self._generate_button.setEnabled(False)
        self._progress.setValue(0)
        self._status_label.setText("Export wird vorbereitet …")
        worker.start()

    def _on_progress(self, percent: int, message: str) -> None:
        self._progress.setValue(percent)
        self._status_label.setText(message)

    def _on_result(self, results: object, output_folder: str) -> None:
        if not isinstance(results, list):
            return
        total_kb = sum(r.file_size_bytes for r in results if isinstance(r, SamplePageExportResult)) / 1024
        self._progress.setValue(100)
        self._status_label.setText(
            f"{len(results)} Seite(n) exportiert nach {output_folder} (gesamt {total_kb:.0f} KB)."
        )
        self._last_output_folder = output_folder
        self._open_folder_button.setEnabled(True)

    def _on_error(self, exc: BaseException) -> None:
        self._status_label.setText(f"Export fehlgeschlagen: {exc}")
        QMessageBox.critical(self, "Export fehlgeschlagen", str(exc))

    def _on_finished(self) -> None:
        self._worker = None
        self._generate_button.setEnabled(True)

    def _open_output_folder(self) -> None:
        if not self._last_output_folder:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_output_folder)):
            QMessageBox.warning(self, "Ordner öffnen", "Der Ausgabeordner konnte nicht geöffnet werden.")
