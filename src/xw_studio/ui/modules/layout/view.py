"""Layout module — QR-Code, Leerseiten, Deckblatt, ISBN."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.layout.service import LayoutToolsService

if TYPE_CHECKING:
    from xw_studio.core.container import Container

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
        self._worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_a5_tab(), "A5 -> A4")
        tabs.addTab(self._build_qr_tab(), "QR-Code")
        tabs.addTab(self._build_blank_tab(), "Leerseiten")
        tabs.addTab(self._build_cover_tab(), "Deckblatt")
        tabs.addTab(self._build_isbn_tab(), "ISBN")
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
    # Tab 2: QR-Code-Generator
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
    # Shared error handler
    # ------------------------------------------------------------------

    def _on_error(self, exc: BaseException) -> None:
        logger.exception("LayoutView background task failed: %s", exc)
        QMessageBox.critical(self, "Fehler", str(exc))

    def _on_worker_finished(self) -> None:
        self._worker = None
