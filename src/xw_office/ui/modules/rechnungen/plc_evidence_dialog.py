"""Read-only shipment evidence with explicit multi-parcel code confirmation."""
from __future__ import annotations

import html
from collections.abc import Callable
from datetime import timezone
from pathlib import Path
from urllib.parse import quote
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTextBrowser, QVBoxLayout,
    QWidget,
)

from xw_office.core.container import Container
from xw_office.repositories.plc_shipment import PlcParcelEvidence, PlcShipmentRepository
from xw_office.core.worker import BackgroundWorker


class PlcEvidenceDialog(QDialog):
    def __init__(
        self, repository: PlcShipmentRepository | Container, *, invoice_id: str,
        invoice_number: str = "", parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository_source = repository
        self._invoice_id = invoice_id
        self._invoice_number = invoice_number
        self._worker: BackgroundWorker | None = None
        self._write_worker: BackgroundWorker | None = None
        self._closing = False
        self._reload_pending = False
        self.setWindowTitle("PLC: Paketinhalt und Sendungsnachweis")
        self.resize(780, 610)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Paketinhalt laut XW-Office beim Erstellen des PLC-Labels. "
            "Die Post-Annahme und Zustellung sind nur in der offiziellen Sendungsverfolgung belegt.", self
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._details = QTextBrowser(self)
        self._details.setOpenExternalLinks(True)
        layout.addWidget(self._details, 1)
        row = QHBoxLayout()
        self._package = QComboBox(self)
        self._package.setMinimumWidth(280)
        self._code = QLineEdit(self)
        self._code.setPlaceholderText("Barcode vom Paketlabel scannen/eingeben")
        self._confirm = QPushButton("Code zuordnen", self)
        self._confirm.clicked.connect(self._confirm_code)
        row.addWidget(self._package)
        row.addWidget(self._code, 1)
        row.addWidget(self._confirm)
        layout.addLayout(row)
        self._import_button = QPushButton("Post-Tracking-XML importieren", self)
        self._import_button.clicked.connect(self._import_tracking)
        layout.addWidget(self._import_button, alignment=Qt.AlignmentFlag.AlignLeft)
        close = QPushButton("Schließen", self)
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._reload()

    def accept(self) -> None:
        if self._write_worker is not None:
            return
        self._closing = True
        super().accept()

    def reject(self) -> None:
        if self._write_worker is not None:
            return
        self._closing = True
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._write_worker is not None:
            event.ignore()
            return
        self._closing = True
        super().closeEvent(event)

    def _reload(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._start_worker(
            lambda: self._repository().list_parcel_evidence(
                invoice_id=self._invoice_id, invoice_number=self._invoice_number
            ),
            self._render,
        )

    def _repository(self) -> PlcShipmentRepository:
        source = self._repository_source
        return source.resolve(PlcShipmentRepository) if isinstance(source, Container) else source

    def _render(self, result: object) -> None:
        if self._closing:
            return
        entries = result if isinstance(result, list) else []
        self._package.clear()
        parts: list[str] = []
        if not entries:
            parts.append("<p>Für diese Rechnung gibt es noch keinen strukturierten PLC-Paketnachweis. "
                         "Ältere Labels und Packlisten bleiben im Archiv verfügbar.</p>")
        last_shipment = ""
        for entry in entries:
            if entry.shipment_id != last_shipment:
                last_shipment = entry.shipment_id
                created_at = entry.created_at
                zone_label = "Datenbankzeit"
                if created_at.tzinfo is not None:
                    created_at = created_at.astimezone(timezone.utc)
                    zone_label = "UTC"
                created = html.escape(created_at.strftime("%d.%m.%Y %H:%M") + f" {zone_label}")
                parts.append(
                    f"<h3>Sendung {html.escape(entry.reference)}</h3>"
                    f"<p>PLC-Label erstellt: {created}; lokaler Status: {html.escape(entry.status)}</p>"
                )
            parts.append(self._parcel_html(entry))
            if entry.available_codes and (entry.package_count > 1 or not entry.tracking_code):
                self._package.addItem(
                    f"{entry.reference} · Paket {entry.package_number}",
                    (entry.shipment_id, entry.package_number),
                )
        self._details.setHtml("".join(parts))
        enabled = self._package.count() > 0
        self._package.setVisible(enabled)
        self._code.setVisible(enabled)
        self._confirm.setVisible(enabled)

    def _set_busy(self, busy: bool) -> None:
        self._import_button.setEnabled(not busy)
        self._confirm.setEnabled(not busy and self._package.count() > 0)
        self._package.setEnabled(not busy)
        self._code.setEnabled(not busy)

    def _show_error(self, exc: Exception) -> None:
        if not self._closing:
            QMessageBox.warning(self, "PLC-Paketnachweis", str(exc))

    def _worker_finished(self, worker: BackgroundWorker) -> None:
        if self._worker is worker:
            self._worker = None
        if self._write_worker is worker:
            self._write_worker = None
        if self._reload_pending and not self._closing:
            self._reload_pending = False
            self._reload()
            return
        if not self._closing:
            self._set_busy(False)

    def _start_worker(
        self,
        job: Callable[[], Any],
        on_result: Callable[[object], None],
        *,
        blocks_close: bool = False,
    ) -> None:
        if self._closing:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        worker = BackgroundWorker(job)
        self._worker = worker
        if blocks_close:
            self._write_worker = worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda current=worker: self._worker_finished(current))
        worker.start()

    @staticmethod
    def _parcel_html(entry: PlcParcelEvidence) -> str:
        title = f"Paket {entry.package_number}/{entry.package_count}"
        if entry.weight_kg is not None:
            title += f" · {entry.weight_kg} kg"
        contents = "".join(
            "<li>" + html.escape(str(item.get("display_quantity") or item.get("quantity") or "?"))
            + " × " + html.escape(str(item.get("name") or "Unbekannt"))
            + (f" ({html.escape(str(item.get('sku')))})" if item.get("sku") else "")
            + "</li>"
            for item in entry.contents
        ) or "<li>Kein Produktinhalt erfasst</li>"
        if entry.tracking_code:
            code = html.escape(entry.tracking_code)
            url = "https://www.post.at/v2/tnt/sendungssuche?snr=" + quote(entry.tracking_code)
            confirmed_at = entry.confirmed_at
            if confirmed_at is not None and confirmed_at.tzinfo is not None:
                confirmed_at = confirmed_at.astimezone(timezone.utc)
            assignment = (
                " (vom Bediener bestätigt am "
                + html.escape(confirmed_at.strftime("%d.%m.%Y %H:%M UTC")) + ")"
                if confirmed_at else " (eindeutig: ein Paket)"
            )
            tracking = f'<a href="{html.escape(url, quote=True)}">{code}</a>{assignment}'
        else:
            tracking = "Noch nicht zugeordnet"
            if entry.available_codes:
                tracking += "; PLC-Codes dieser Sendung: " + ", ".join(
                    html.escape(code) for code in entry.available_codes
                )
        pdf_note = "Packlisten-PDF gesichert" if entry.packing_pdf_sha256 else "Kein Packlisten-PDF nachgewiesen"
        accepted = min((event.occurred_at for event in entry.events if event.event_type == "ANA"), default=None)
        accepted_abroad = min((event.occurred_at for event in entry.events if event.event_type == "ANI"), default=None)
        delivered = max((event.occurred_at for event in entry.events if event.event_type == "ZUS"), default=None)
        acceptance_note = (
            "Post-Annahme: " + accepted.strftime("%d.%m.%Y %H:%M")
            if accepted else "Post-Annahme: nicht aus importierten Ereignissen belegt"
        )
        if accepted_abroad:
            acceptance_note += "; Annahme im Ausland: " + accepted_abroad.strftime("%d.%m.%Y %H:%M")
        delivery_note = (
            "Zustellung: " + delivered.strftime("%d.%m.%Y %H:%M")
            if delivered else "Zustellung: nicht aus importierten Ereignissen belegt"
        )
        events = "".join(
            "<li>" + html.escape(event.occurred_at.strftime("%d.%m.%Y %H:%M:%S"))
            + " · " + html.escape(
                "Elektronisch angekündigt (AVI)" if event.event_type == "AVI"
                else "Post-Annahme (ANA)" if event.event_type == "ANA"
                else "Annahme im Ausland (ANI)" if event.event_type == "ANI"
                else "Zustellung (ZUS)" if event.event_type == "ZUS"
                else event.event_type
            )
            + (" / " + html.escape(event.event_reason) if event.event_reason else "")
            + (" · " + html.escape(event.event_city or event.event_postal_code)
               if event.event_city or event.event_postal_code else "")
            + " · XML-SHA-256 " + html.escape(event.source_sha256[:12]) + "…</li>"
            for event in entry.events
        )
        event_note = (
            "<p>Post-Ereignisse (Zeit laut Originaldatei):</p><ul>" + events + "</ul>"
            if events else "<p>Keine Post-Ereignisse importiert</p>"
        )
        return (
            f"<h4>{html.escape(title)}</h4><ul>{contents}</ul>"
            f"<p>Tracking: {tracking}<br>{pdf_note}<br>{acceptance_note}<br>{delivery_note}<br>"
            "Offizielle Details über den Tracking-Link prüfen.</p>" + event_note
        )

    def _import_tracking(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self, "Originale Post-Trackingdatei auswaehlen", "", "Post-Tracking XML (*.xml)"
        )
        if not filename:
            return

        def job() -> int:
            return self._repository().import_post_tracking_xml(
                Path(filename).read_bytes(),
                invoice_id=self._invoice_id,
                invoice_number=self._invoice_number,
            )

        def on_imported(result: object) -> None:
            if self._closing:
                return
            count = result if isinstance(result, int) else 0
            QMessageBox.information(
                self,
                "Post-Tracking",
                f"{count} neue Post-Ereignisse fuer diese Rechnung importiert.",
            )
            self._reload_pending = True

        self._start_worker(job, on_imported, blocks_close=True)

    def _confirm_code(self) -> None:
        selection = self._package.currentData()
        if not selection:
            return
        shipment_id, package_number = selection
        tracking_code = self._code.text().strip()

        def job() -> bool:
            return self._repository().confirm_parcel_code(
                shipment_id=shipment_id,
                package_number=package_number,
                tracking_code=tracking_code,
            )

        def on_confirmed(result: object) -> None:
            if self._closing:
                return
            if result is not True:
                QMessageBox.warning(
                    self,
                    "PLC-Code",
                    "Der Code gehoert nicht zu dieser Sendung oder ist bereits einem anderen Paket zugeordnet.",
                )
                return
            self._code.clear()
            self._reload_pending = True

        self._start_worker(job, on_confirmed, blocks_close=True)
