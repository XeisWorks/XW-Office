"""Layout module — QR-Code, Leerseiten, Deckblatt, ISBN."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameGeneratorRequest,
)
from xw_office.services.filename_generator.service import (
    INSTRUMENT_SUGGESTIONS,
    ROLE_LABELS,
    FilenameGeneratorService,
)
from xw_office.services.layout.service import LayoutToolsService, SplitLandscapeResult
from xw_office.services.qr_codes.service import QrCodeService
from xw_office.ui.modules.layout.qr_batch_dialog import QrCodeBatchDialog
from xw_office.ui.modules.layout.qr_settings_dialog import QrSettingsDialog

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)


class LayoutView(QWidget):
    """Layout-Werkzeuge: QR-Code, Leerseiten, Deckblatt, ISBN-Validierung."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._qr_bytes: bytes | None = None
        self._blank_source_path: str | None = None
        self._blank_result: bytes | None = None
        self._cover_result: bytes | None = None
        self._a5_source_path: str | None = None
        self._a5_output_path: str | None = None
        self._landscape_source_path: str | None = None
        self._landscape_output_path: str | None = None
        self._watermark_source_path: str | None = None
        self._watermark_output_dir: str = r"C:\Users\bernh\OneDrive - XeisWorks\02 XeisWorks\24 Digitale Lizensierung"
        self._worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_a5_tab(), "A5 -> A4")
        tabs.addTab(self._build_landscape_split_tab(), "Querformat teilen")
        tabs.addTab(self._build_qr_tab(), "QR-Code")
        tabs.addTab(self._build_qr_series_tab(), "QR-Code-Serien")
        tabs.addTab(self._build_filename_generator_tab(), "Dateinamen-Generator")
        tabs.addTab(self._build_blank_tab(), "Leerseiten")
        tabs.addTab(self._build_cover_tab(), "Deckblatt")
        tabs.addTab(self._build_isbn_tab(), "ISBN")
        tabs.addTab(self._build_watermark_tab(), "Wasserzeichen seitlich A4")
        root.addWidget(tabs)

    # ------------------------------------------------------------------
    # Tab 1: A5 verdoppeln auf A4
    # ------------------------------------------------------------------

    def _build_a5_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        file_group = QGroupBox("PDF-Dateien")
        file_layout = QFormLayout(file_group)

        source_row = QHBoxLayout()
        self._a5_source_lbl = QLabel("(keine Datei gewaehlt)")
        self._a5_source_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        source_row.addWidget(self._a5_source_lbl)
        source_btn = QPushButton("PDF oeffnen...")
        source_btn.clicked.connect(self._pick_a5_source)
        source_row.addWidget(source_btn)
        file_layout.addRow("Quelle:", source_row)

        output_row = QHBoxLayout()
        self._a5_output_lbl = QLabel("(wird nach Dateiauswahl vorgeschlagen)")
        self._a5_output_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        output_row.addWidget(self._a5_output_lbl)
        output_btn = QPushButton("Ziel waehlen...")
        output_btn.clicked.connect(self._pick_a5_output)
        output_row.addWidget(output_btn)
        file_layout.addRow("Ausgabe:", output_row)
        lay.addWidget(file_group)

        options = QFormLayout()
        self._a5_margin = QDoubleSpinBox()
        self._a5_margin.setRange(0.0, 25.0)
        self._a5_margin.setDecimals(1)
        self._a5_margin.setSingleStep(0.5)
        self._a5_margin.setSuffix(" mm")
        self._a5_margin.setValue(0.0)
        options.addRow("Sicherheitsrand je A5-Haelfte:", self._a5_margin)
        lay.addLayout(options)

        btn_row = QHBoxLayout()
        self._a5_run_btn = QPushButton("A5 verdoppeln auf A4")
        self._a5_run_btn.clicked.connect(self._run_a5_duplicate)
        btn_row.addWidget(self._a5_run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._a5_status = QLabel("Bereit")
        self._a5_status.setWordWrap(True)
        lay.addWidget(self._a5_status)

        info = QLabel(
            "Erzeugt pro Quellseite ein A4-Blatt mit identischer Kopie oben und unten. "
            "Gedrehte Quellseiten werden vor der Platzierung rotationsneutral verarbeitet."
        )
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch()
        return page

    def _pick_a5_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "A5-PDF oeffnen", "", "PDF (*.pdf)")
        if not path:
            return
        self._a5_source_path = path
        self._a5_source_lbl.setText(path)
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)
        self._a5_output_path = str(svc.default_a5_duplicate_output_path(path))
        self._a5_output_lbl.setText(self._a5_output_path)
        self._a5_status.setText("Bereit")

    def _pick_a5_output(self) -> None:
        start = self._a5_output_path or "noten_A4-2x.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "A4-Ausgabe speichern", start, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"
        self._a5_output_path = path
        self._a5_output_lbl.setText(path)

    def _run_a5_duplicate(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._a5_source_path:
            QMessageBox.warning(self, "A5 -> A4", "Bitte zuerst eine PDF-Datei oeffnen.")
            return
        if not self._a5_output_path:
            QMessageBox.warning(self, "A5 -> A4", "Bitte ein Ausgabeziel waehlen.")
            return

        source = self._a5_source_path
        output = self._a5_output_path
        if Path(output).exists():
            answer = QMessageBox.question(
                self,
                "A5 -> A4",
                f"Die Ausgabedatei existiert bereits:\n{output}\n\nUeberschreiben?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._a5_status.setText("Abgebrochen.")
                return

        margin_mm = float(self._a5_margin.value())
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)

        def job() -> str:
            return str(svc.duplicate_a5_to_a4(source, output_pdf=output, margin_mm=margin_mm, overwrite=True))

        self._a5_run_btn.setEnabled(False)
        self._a5_status.setText("Verarbeite PDF...")
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_a5_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(lambda: self._a5_run_btn.setEnabled(True))
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_a5_done(self, data: object) -> None:
        if not isinstance(data, str):
            return
        self._a5_status.setText(f"Gespeichert: {data}")
        QMessageBox.information(self, "Fertig", f"A5 -> A4 gespeichert:\n{data}")

    # ------------------------------------------------------------------
    # Tab 2: Querformatseiten in A4-Hochformatseiten teilen
    # ------------------------------------------------------------------

    def _build_landscape_split_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        file_group = QGroupBox("PDF-Dateien")
        file_layout = QFormLayout(file_group)

        source_row = QHBoxLayout()
        self._landscape_source_lbl = QLabel("(keine Datei gewaehlt)")
        self._landscape_source_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        source_row.addWidget(self._landscape_source_lbl)
        source_btn = QPushButton("PDF oeffnen...")
        source_btn.clicked.connect(self._pick_landscape_source)
        source_row.addWidget(source_btn)
        file_layout.addRow("Quelle:", source_row)

        output_row = QHBoxLayout()
        self._landscape_output_lbl = QLabel("(wird nach Dateiauswahl vorgeschlagen)")
        self._landscape_output_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        output_row.addWidget(self._landscape_output_lbl)
        output_btn = QPushButton("Ziel waehlen...")
        output_btn.clicked.connect(self._pick_landscape_output)
        output_row.addWidget(output_btn)
        file_layout.addRow("Ausgabe:", output_row)
        lay.addWidget(file_group)

        btn_row = QHBoxLayout()
        self._landscape_run_btn = QPushButton("Querformatseiten teilen")
        self._landscape_run_btn.clicked.connect(self._run_landscape_split)
        btn_row.addWidget(self._landscape_run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._landscape_status = QLabel("Bereit")
        self._landscape_status.setWordWrap(True)
        lay.addWidget(self._landscape_status)

        info = QLabel(
            "Teilt nur echte Querformatseiten in linke und rechte A4-Hochformatseite. "
            "Hochformatseiten am Anfang, Ende oder dazwischen werden unveraendert uebernommen."
        )
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch()
        return page

    def _pick_landscape_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF oeffnen", "", "PDF (*.pdf)")
        if not path:
            return
        self._landscape_source_path = path
        self._landscape_source_lbl.setText(path)
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)
        self._landscape_output_path = str(svc.default_landscape_split_output_path(path))
        self._landscape_output_lbl.setText(self._landscape_output_path)
        self._landscape_status.setText("Bereit")

    def _pick_landscape_output(self) -> None:
        start = self._landscape_output_path or "seiten_A4-hoch-geteilt.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Ausgabe speichern", start, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"
        self._landscape_output_path = path
        self._landscape_output_lbl.setText(path)

    def _run_landscape_split(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._landscape_source_path:
            QMessageBox.warning(self, "Querformat teilen", "Bitte zuerst eine PDF-Datei oeffnen.")
            return
        if not self._landscape_output_path:
            QMessageBox.warning(self, "Querformat teilen", "Bitte ein Ausgabeziel waehlen.")
            return

        source = self._landscape_source_path
        output = self._landscape_output_path
        if Path(output).exists():
            answer = QMessageBox.question(
                self,
                "Querformat teilen",
                f"Die Ausgabedatei existiert bereits:\n{output}\n\nUeberschreiben?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._landscape_status.setText("Abgebrochen.")
                return

        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)

        def job() -> SplitLandscapeResult:
            return svc.split_landscape_pages_to_a4_portrait(source, output_pdf=output, overwrite=True)

        self._landscape_run_btn.setEnabled(False)
        self._landscape_status.setText("Verarbeite PDF...")
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_landscape_split_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(lambda: self._landscape_run_btn.setEnabled(True))
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_landscape_split_done(self, data: object) -> None:
        if not isinstance(data, SplitLandscapeResult):
            return
        message = (
            f"Gespeichert: {data.output_path}\n"
            f"Quelle: {data.source_pages} Seiten, Ausgabe: {data.output_pages} Seiten, "
            f"geteilt: {data.split_pages}, unveraendert: {data.copied_pages}"
        )
        self._landscape_status.setText(message)
        QMessageBox.information(self, "Fertig", message)

    # ------------------------------------------------------------------
    # Tab 3: QR-Code-Generator
    # ------------------------------------------------------------------

    def _build_qr_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QFormLayout()
        self._qr_text = QLineEdit()
        self._qr_text.setPlaceholderText("URL oder Text fuer QR-Code")
        form.addRow("Inhalt:", self._qr_text)

        self._qr_scale = QSpinBox()
        self._qr_scale.setRange(1, 20)
        self._qr_scale.setValue(6)
        form.addRow("Groesse (Skalierung):", self._qr_scale)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        gen_btn = QPushButton("QR-Code generieren")
        gen_btn.clicked.connect(self._generate_qr)
        btn_row.addWidget(gen_btn)
        self._qr_save_btn = QPushButton("Als PNG speichern")
        self._qr_save_btn.setEnabled(False)
        self._qr_save_btn.clicked.connect(self._save_qr)
        btn_row.addWidget(self._qr_save_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._qr_preview = QLabel("(Vorschau erscheint hier)")
        self._qr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_preview.setMinimumHeight(220)
        self._qr_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._qr_preview.setObjectName("qrPreviewLabel")
        lay.addWidget(self._qr_preview)

        lay.addStretch()
        return page

    def _generate_qr(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        text = self._qr_text.text().strip()
        if not text:
            QMessageBox.warning(self, "QR-Code", "Bitte einen Text oder eine URL eingeben.")
            return
        scale = self._qr_scale.value()
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)

        def job() -> bytes:
            return svc.generate_qr_png(text, scale=scale)

        self._qr_preview.setText("Generiere...")
        self._qr_save_btn.setEnabled(False)
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_qr_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_qr_done(self, data: object) -> None:
        if not isinstance(data, bytes):
            return
        self._qr_bytes = data
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            self._qr_preview.setPixmap(
                px.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        self._qr_save_btn.setEnabled(True)

    def _save_qr(self) -> None:
        if not self._qr_bytes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "QR-Code speichern", "qrcode.png", "PNG (*.png)")
        if path:
            try:
                with open(path, "wb") as fh:
                    fh.write(self._qr_bytes)
                QMessageBox.information(self, "Gespeichert", f"QR-Code gespeichert:\n{path}")
            except OSError as exc:
                QMessageBox.critical(self, "Fehler", str(exc))

    # ------------------------------------------------------------------
    # Tab: QR-Code-Serien (Batch-Generator fuer die Excel-Register)
    # ------------------------------------------------------------------

    def _build_qr_series_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel(
            "Erzeugt ganze QR-Code-Serien (Ganze Skala, Gesamtspielchen, Ungerade/Gerade Zahlen, "
            "Jede 4. Zahl) mit Mittellogo, nativ und offline - reproduziert die Excel-Arbeitsmappe "
            "\"QR-Codes Online.xlsx\"."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        generate_btn = QPushButton("QR-Code-Serie erzeugen...")
        generate_btn.clicked.connect(self._open_qr_batch_dialog)
        lay.addWidget(generate_btn)

        settings_btn = QPushButton("QR-Code-Einstellungen...")
        settings_btn.clicked.connect(self._open_qr_settings_dialog)
        lay.addWidget(settings_btn)

        self._open_qr_output_dir_btn = QPushButton("Letzten Ausgabeordner oeffnen")
        self._open_qr_output_dir_btn.clicked.connect(self._open_last_qr_output_dir)
        lay.addWidget(self._open_qr_output_dir_btn)
        self._refresh_qr_output_dir_button()

        lay.addStretch()
        return page

    def _refresh_qr_output_dir_button(self) -> None:
        svc: QrCodeService = self._container.resolve(QrCodeService)
        last_dir = svc.load_settings().last_output_directory
        self._open_qr_output_dir_btn.setEnabled(bool(last_dir) and Path(last_dir).is_dir())

    def _open_qr_batch_dialog(self) -> None:
        dialog = QrCodeBatchDialog(self._container, self)
        dialog.exec()
        self._refresh_qr_output_dir_button()

    def _open_qr_settings_dialog(self) -> None:
        svc: QrCodeService = self._container.resolve(QrCodeService)
        dialog = QrSettingsDialog(svc, svc.load_settings(), self)
        dialog.exec()

    def _open_last_qr_output_dir(self) -> None:
        svc: QrCodeService = self._container.resolve(QrCodeService)
        last_dir = svc.load_settings().last_output_directory
        if not last_dir or not Path(last_dir).is_dir():
            QMessageBox.information(self, "QR-Code-Serien", "Es ist noch kein Ausgabeordner gespeichert.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(last_dir)):
            QMessageBox.warning(self, "QR-Code-Serien", "Der Ordner konnte nicht geoeffnet werden.")

    # ------------------------------------------------------------------
    # Tab 2: Leerseiten einfuegen
    # ------------------------------------------------------------------

    def _build_blank_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        grp = QGroupBox("PDF-Datei")
        g_lay = QHBoxLayout(grp)
        self._blank_file_lbl = QLabel("(keine Datei gewaehlt)")
        self._blank_file_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        g_lay.addWidget(self._blank_file_lbl)
        open_btn = QPushButton("Datei oeffnen...")
        open_btn.clicked.connect(self._pick_blank_source)
        g_lay.addWidget(open_btn)
        lay.addWidget(grp)

        form = QFormLayout()
        self._blank_positions = QLineEdit()
        self._blank_positions.setPlaceholderText("z. B. 2, 5, 8  (Seitennummern nach dem Einsetzen)")
        form.addRow("Leerseiten nach Seite:", self._blank_positions)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("Leerseiten einfuegen + speichern")
        run_btn.clicked.connect(self._run_blank_insert)
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._blank_status = QLabel("")
        lay.addWidget(self._blank_status)
        lay.addStretch()
        return page

    def _pick_blank_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF oeffnen", "", "PDF (*.pdf)")
        if not path:
            return
        self._blank_file_lbl.setText(path)
        self._blank_source_path = path

    def _run_blank_insert(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._blank_source_path:
            QMessageBox.warning(self, "Leerseiten", "Bitte zuerst eine PDF-Datei oeffnen.")
            return
        raw = self._blank_positions.text().strip()
        try:
            positions = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            QMessageBox.warning(self, "Leerseiten", "Ungueltige Seitennummern. Komma-getrennte Zahlen erwartet.")
            return
        if not positions:
            QMessageBox.warning(self, "Leerseiten", "Bitte mindestens eine Seitennummer angeben.")
            return

        source_path = self._blank_source_path
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)

        def job() -> bytes:
            src = Path(source_path).read_bytes()
            return svc.insert_blank_pages(src, insert_after=positions)

        self._blank_status.setText("Verarbeite...")
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_blank_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_blank_done(self, data: object) -> None:
        if not isinstance(data, bytes):
            return
        self._blank_result = data
        path, _ = QFileDialog.getSaveFileName(
            self, "Ergebnis-PDF speichern", "output_with_blanks.pdf", "PDF (*.pdf)"
        )
        if path:
            try:
                with open(path, "wb") as fh:
                    fh.write(self._blank_result)
                self._blank_status.setText(f"Gespeichert: {path}")
                QMessageBox.information(self, "Fertig", f"PDF gespeichert:\n{path}")
            except OSError as exc:
                QMessageBox.critical(self, "Fehler", str(exc))
        else:
            self._blank_status.setText("Abgebrochen.")

    # ------------------------------------------------------------------
    # Tab 3: Deckblatt generieren
    # ------------------------------------------------------------------

    def _build_cover_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QFormLayout()
        self._cover_title = QLineEdit()
        self._cover_title.setPlaceholderText("Haupttitel")
        form.addRow("Titel:", self._cover_title)

        self._cover_subtitle = QLineEdit()
        self._cover_subtitle.setPlaceholderText("Untertitel (optional)")
        form.addRow("Untertitel:", self._cover_subtitle)

        self._cover_author = QLineEdit()
        self._cover_author.setPlaceholderText("Autorenname (optional)")
        form.addRow("Autor/in:", self._cover_author)

        self._cover_isbn = QLineEdit()
        self._cover_isbn.setPlaceholderText("ISBN (optional)")
        form.addRow("ISBN:", self._cover_isbn)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        gen_btn = QPushButton("Deckblatt erstellen + speichern")
        gen_btn.clicked.connect(self._generate_cover)
        btn_row.addWidget(gen_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._cover_status = QLabel("")
        lay.addWidget(self._cover_status)
        lay.addStretch()
        return page

    def _generate_cover(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        title = self._cover_title.text().strip()
        if not title:
            QMessageBox.warning(self, "Deckblatt", "Bitte einen Titel eingeben.")
            return
        subtitle = self._cover_subtitle.text().strip()
        author = self._cover_author.text().strip()
        isbn = self._cover_isbn.text().strip()
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)

        def job() -> bytes:
            return svc.generate_cover_pdf(title, subtitle=subtitle, author=author, isbn=isbn)

        self._cover_status.setText("Erstelle Deckblatt...")
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_cover_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_cover_done(self, data: object) -> None:
        if not isinstance(data, bytes):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Deckblatt-PDF speichern", "deckblatt.pdf", "PDF (*.pdf)"
        )
        if path:
            try:
                with open(path, "wb") as fh:
                    fh.write(data)
                self._cover_status.setText(f"Gespeichert: {path}")
                QMessageBox.information(self, "Fertig", f"Deckblatt gespeichert:\n{path}")
            except OSError as exc:
                QMessageBox.critical(self, "Fehler", str(exc))
        else:
            self._cover_status.setText("Abgebrochen.")

    # ------------------------------------------------------------------
    # Tab 4: ISBN-Validator
    # ------------------------------------------------------------------

    def _build_isbn_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QFormLayout()
        self._isbn_input = QLineEdit()
        self._isbn_input.setPlaceholderText("ISBN-10 oder ISBN-13 eingeben")
        self._isbn_input.returnPressed.connect(self._validate_isbn)
        form.addRow("ISBN:", self._isbn_input)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        val_btn = QPushButton("Validieren")
        val_btn.clicked.connect(self._validate_isbn)
        btn_row.addWidget(val_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._isbn_result = QLabel("")
        self._isbn_result.setWordWrap(True)
        self._isbn_result.setObjectName("isbnResultLabel")
        lay.addWidget(self._isbn_result)

        info = QLabel(
            "Prueft ISBN-10 und ISBN-13 inkl. Pruefziffer.\n"
            "Bei ISBN-10 wird auch die ISBN-13-Variante angezeigt."
        )
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch()
        return page

    def _validate_isbn(self) -> None:
        raw = self._isbn_input.text().strip()
        if not raw:
            self._isbn_result.setText("Bitte eine ISBN eingeben.")
            return
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)
        ok, msg = svc.validate_isbn(raw)
        palette_role = "color: #4ade80;" if ok else "color: #f87171;"
        self._isbn_result.setStyleSheet(palette_role)
        self._isbn_result.setText(msg)

    # ------------------------------------------------------------------
    # Tab 6: seitliches A4-Wasserzeichen
    # ------------------------------------------------------------------

    def _build_watermark_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        file_group = QGroupBox("PDF-Dateien")
        file_layout = QFormLayout(file_group)

        source_row = QHBoxLayout()
        self._watermark_source_lbl = QLabel("(keine Datei gewaehlt)")
        self._watermark_source_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        source_row.addWidget(self._watermark_source_lbl)
        source_btn = QPushButton("PDF oeffnen...")
        source_btn.clicked.connect(self._pick_watermark_source)
        source_row.addWidget(source_btn)
        file_layout.addRow("Quelle:", source_row)

        output_row = QHBoxLayout()
        self._watermark_output_lbl = QLabel(self._watermark_output_dir)
        self._watermark_output_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        output_row.addWidget(self._watermark_output_lbl)
        output_btn = QPushButton("Ordner waehlen...")
        output_btn.clicked.connect(self._pick_watermark_output_dir)
        output_row.addWidget(output_btn)
        file_layout.addRow("Ausgabeordner:", output_row)
        lay.addWidget(file_group)

        form = QFormLayout()
        self._watermark_name = QLineEdit()
        self._watermark_name.setPlaceholderText("Vorname Nachname")
        form.addRow("Lizenzname:", self._watermark_name)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        self._watermark_run_btn = QPushButton("Lizenzierte PDF erzeugen")
        self._watermark_run_btn.clicked.connect(self._run_watermark)
        btn_row.addWidget(self._watermark_run_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._watermark_status = QLabel("Bereit")
        self._watermark_status.setWordWrap(True)
        lay.addWidget(self._watermark_status)
        lay.addStretch()
        return page

    def _pick_watermark_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF oeffnen", "", "PDF (*.pdf)")
        if not path:
            return
        self._watermark_source_path = path
        self._watermark_source_lbl.setText(path)
        self._watermark_status.setText("Bereit")

    def _pick_watermark_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Ausgabeordner waehlen", self._watermark_output_dir)
        if not path:
            return
        self._watermark_output_dir = path
        self._watermark_output_lbl.setText(path)

    def _run_watermark(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._watermark_source_path:
            QMessageBox.warning(self, "Wasserzeichen", "Bitte zuerst eine PDF-Datei oeffnen.")
            return
        name = self._watermark_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Wasserzeichen", "Bitte Vorname und Nachname eingeben.")
            return
        svc: LayoutToolsService = self._container.resolve(LayoutToolsService)
        source = self._watermark_source_path
        output_dir = self._watermark_output_dir

        def job() -> str:
            return str(svc.watermark_side_a4_pdf(source, output_dir=output_dir, user_name=name))

        self._watermark_run_btn.setEnabled(False)
        self._watermark_status.setText("Erzeuge lizenzierte PDF...")
        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_watermark_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(lambda: self._watermark_run_btn.setEnabled(True))
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_watermark_done(self, data: object) -> None:
        if not isinstance(data, str):
            return
        self._watermark_status.setText(f"Gespeichert: {data}")
        QMessageBox.information(self, "Fertig", f"Lizenzierte PDF gespeichert:\n{data}")

    # ------------------------------------------------------------------
    # Tab: Dateinamen-Generator (MH-AudioPlayer MH-Tracks-Konvention)
    # ------------------------------------------------------------------

    def _build_filename_generator_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel(
            "Erzeugt Dateinamen nach der MH-Tracks-Konvention des MH-AudioPlayer "
            "(edition__track__instrument__rolle.mp3), z. B. sk-t__01__btb__practice.mp3. "
            "Es wird nichts umbenannt - die Liste ist zum manuellen Ueberschreiben per "
            "Kopieren/Einfuegen gedacht."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        form_group = QGroupBox("Angaben")
        form = QFormLayout(form_group)

        self._fname_edition_edit = QLineEdit()
        self._fname_edition_edit.setPlaceholderText("z. B. sk-t")
        form.addRow("Edition-Slug:", self._fname_edition_edit)

        self._fname_instrument_combo = QComboBox()
        self._fname_instrument_combo.setEditable(True)
        self._fname_instrument_combo.addItems(INSTRUMENT_SUGGESTIONS)
        form.addRow("Instrument-Slug:", self._fname_instrument_combo)

        track_row = QHBoxLayout()
        self._fname_track_start = QSpinBox()
        self._fname_track_start.setRange(1, 999)
        self._fname_track_start.setValue(1)
        track_row.addWidget(QLabel("Start:"))
        track_row.addWidget(self._fname_track_start)

        self._fname_track_end = QSpinBox()
        self._fname_track_end.setRange(1, 999)
        self._fname_track_end.setValue(8)
        track_row.addWidget(QLabel("Ende:"))
        track_row.addWidget(self._fname_track_end)

        self._fname_track_width = QSpinBox()
        self._fname_track_width.setRange(1, 4)
        self._fname_track_width.setValue(2)
        track_row.addWidget(QLabel("Mindestbreite:"))
        track_row.addWidget(self._fname_track_width)
        form.addRow("Tracks:", track_row)

        roles_row = QHBoxLayout()
        self._fname_role_practice = QCheckBox(f"{ROLE_LABELS['practice']} (practice)")
        self._fname_role_practice.setChecked(True)
        roles_row.addWidget(self._fname_role_practice)
        self._fname_role_performance = QCheckBox(f"{ROLE_LABELS['performance']} (performance)")
        roles_row.addWidget(self._fname_role_performance)
        self._fname_role_teacher = QCheckBox(f"{ROLE_LABELS['teacher']} (teacher)")
        roles_row.addWidget(self._fname_role_teacher)
        form.addRow("Rollen:", roles_row)

        self._fname_extra_roles_edit = QLineEdit()
        self._fname_extra_roles_edit.setPlaceholderText("weitere Rollen, kommagetrennt, z. B. voice, mix")
        form.addRow("Weitere Rollen:", self._fname_extra_roles_edit)

        lay.addWidget(form_group)

        generate_btn = QPushButton("Dateinamen erzeugen")
        generate_btn.clicked.connect(self._run_filename_generator)
        lay.addWidget(generate_btn)

        self._fname_output = QPlainTextEdit()
        self._fname_output.setReadOnly(True)
        self._fname_output.setPlaceholderText("(noch keine Dateinamen erzeugt)")
        lay.addWidget(self._fname_output, stretch=1)

        copy_btn = QPushButton("In Zwischenablage kopieren")
        copy_btn.clicked.connect(self._copy_filename_generator_output)
        lay.addWidget(copy_btn)

        self._fname_status = QLabel("Bereit")
        self._fname_status.setWordWrap(True)
        lay.addWidget(self._fname_status)

        return page

    def _run_filename_generator(self) -> None:
        roles: list[str] = []
        if self._fname_role_practice.isChecked():
            roles.append("practice")
        if self._fname_role_performance.isChecked():
            roles.append("performance")
        if self._fname_role_teacher.isChecked():
            roles.append("teacher")
        extra_roles = [part.strip() for part in self._fname_extra_roles_edit.text().split(",") if part.strip()]
        roles.extend(extra_roles)

        svc: FilenameGeneratorService = self._container.resolve(FilenameGeneratorService)
        request = FilenameGeneratorRequest(
            edition_slug=self._fname_edition_edit.text(),
            instrument_slug=self._fname_instrument_combo.currentText(),
            track_start=self._fname_track_start.value(),
            track_end=self._fname_track_end.value(),
            roles=tuple(roles),
            track_width=self._fname_track_width.value(),
        )
        try:
            names = svc.build_filenames(request)
        except FilenameGeneratorError as exc:
            self._fname_output.setPlainText("")
            self._fname_status.setText(f"Fehler: {exc}")
            return

        self._fname_output.setPlainText("\n".join(names))
        self._fname_status.setText(f"{len(names)} Dateinamen erzeugt.")

    def _copy_filename_generator_output(self) -> None:
        text = self._fname_output.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._fname_status.setText("In die Zwischenablage kopiert.")

    # ------------------------------------------------------------------
    # Shared error handler
    # ------------------------------------------------------------------

    def _on_error(self, exc: BaseException) -> None:
        logger.exception("LayoutView background task failed: %s", exc)
        QMessageBox.critical(self, "Fehler", str(exc))

    def _on_worker_finished(self) -> None:
        self._worker = None
