"""PLC label export dialog (ported from legacy Tkinter flow)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.plc.polling import (
    DEFAULT_PLC_IMPORT_DIR,
    DEFAULT_TEST_PLC_IMPORT_DIR,
    PlcConfig,
    write_import_file,
)
from xw_studio.services.plc.models import (
    EU_COUNTRIES,
    PlcCustomsArticle,
    PlcParcel,
    PlcShipmentDraft,
    build_polling_lines,
    clean_reference,
    parse_shipment_address_lines,
)
from xw_studio.services.plc.pricing import quote_plc_price
from xw_studio.services.plc.label_archive import PlcLabelArchive
from xw_studio.services.plc.service import PlcDuplicateShipmentError, PlcShipmentService
from xw_studio.services.plc.webservice import PlcWebserviceResult, webservice_settings_from_secrets
from xw_studio.services.printing.print_jobs import PdfPrintJob
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.shipping.countries import (
    country_name_en,
    country_names_en,
    country_search_names,
)
from xw_studio.services.wix.client import WixOrderItem, WixOrdersClient

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_EU_PRODUCT_ID = "45"
_DEFAULT_ITEM_WEIGHT_KG = 0.30


@dataclass
class _PlcDialogContext:
    order_number: str
    address_lines: list[str]
    weight_kg: float
    items: list[WixOrderItem]
    email: str = ""


@dataclass(frozen=True)
class _PlcSendResult:
    transport: str
    reference: str
    webservice_result: PlcWebserviceResult | None = None
    polling_path: str = ""


class PlcLabelPrintDialog(QDialog):
    _mail_ref_counters: dict[str, int] = {}

    def __init__(
        self,
        container: Container,
        summary: InvoiceSummary | None,
        parent: QWidget | None = None,
        *,
        address_override_lines: list[str] | None = None,
        recipient_email: str = "",
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._manual_entry = summary is None
        self._summary = summary or InvoiceSummary(id="")
        self._load_worker: BackgroundWorker | None = None
        self._send_worker: BackgroundWorker | None = None
        self._context = _PlcDialogContext(order_number="", address_lines=[], weight_kg=0.0, items=[])
        self._label_archive = PlcLabelArchive()
        self._product_catalog = self._load_products()
        self._product_user_set = False
        self._address_edited = bool(address_override_lines)
        self._weight_user_set = False

        self.setWindowTitle("PLC Label Print")
        self.setMinimumWidth(700)
        self._build_ui()
        self._recipient_email.setText(str(recipient_email or "office@xeisworks.at").strip())
        if address_override_lines and not self._manual_entry:
            self._address_edit.blockSignals(True)
            self._address_edit.setPlainText("\n".join(str(line).strip() for line in address_override_lines if str(line).strip()))
            self._address_edit.blockSignals(False)
            self._status.setText("Adresse aus VERSANDADRESSE übernommen")
        if self._manual_entry:
            self._sync_product_options()
            self._update_customs_visibility()
            self._status.setText("Adresse und Paketgewicht eingeben")
        else:
            self._load_context()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        price_row = QHBoxLayout()
        price_row.addStretch()
        self._price_label = QLabel("Preis: —")
        self._price_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #0f766e; padding: 4px 8px;"
        )
        price_row.addWidget(self._price_label)
        root.addLayout(price_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        mode_row = QHBoxLayout()
        self._mode_live = QRadioButton("LIVE")
        self._mode_test = QRadioButton("TEST")
        self._mode_live.setChecked(True)
        mode_row.addWidget(self._mode_live)
        mode_row.addWidget(self._mode_test)
        mode_row.addStretch()
        mode_wrap = QWidget()
        mode_wrap.setLayout(mode_row)
        form.addRow("Modus:", mode_wrap)

        self._transport_combo = QComboBox()
        self._transport_combo.addItem("Webservice (direkt, Standard)", "webservice")
        self._transport_combo.addItem("Dateiimport (Ondot-Fallback)", "polling")
        form.addRow("Ãœbertragungsweg:", self._transport_combo)

        self._product_combo = QComboBox()
        self._product_combo.currentTextChanged.connect(self._on_product_selected)
        form.addRow("Versandprodukt:", self._product_combo)

        self._weight_edit = QLineEdit()
        self._weight_edit.setPlaceholderText("z.B. 0,45")
        self._weight_edit.textChanged.connect(self._on_weight_edit)
        form.addRow("Gewicht (kg):", self._weight_edit)

        self._customs_edit = QPlainTextEdit()
        self._customs_edit.setPlaceholderText("Zollbeschreibung")
        self._customs_edit.setFixedHeight(72)
        form.addRow("Zollbeschreibung:", self._customs_edit)

        if self._manual_entry:
            self._company_edit = QLineEdit()
            self._company_edit.setPlaceholderText("FIRMA (optional)")
            self._company_edit.textChanged.connect(self._on_address_edit)
            form.addRow("Firma:", self._company_edit)

            self._name_edit = QLineEdit()
            self._name_edit.setPlaceholderText("VOR- UND NACHNAME")
            self._name_edit.textChanged.connect(self._on_address_edit)
            form.addRow("Name:", self._name_edit)

            self._street_edit = QLineEdit()
            self._street_edit.setPlaceholderText("STRASSE UND HAUSNUMMER")
            self._street_edit.textChanged.connect(self._on_address_edit)
            form.addRow("Straße:", self._street_edit)

            self._postal_city_edit = QLineEdit()
            self._postal_city_edit.setPlaceholderText("PLZ ORT")
            self._postal_city_edit.textChanged.connect(self._on_address_edit)
            form.addRow("PLZ / Ort:", self._postal_city_edit)

            self._country_combo = QComboBox()
            self._country_combo.setEditable(True)
            self._country_combo.addItems(country_names_en())
            self._country_combo.setCurrentIndex(-1)
            country_line_edit = self._country_combo.lineEdit()
            if country_line_edit is not None:
                country_line_edit.setPlaceholderText("LAND (English) – z. B. Austria")
            country_completer = QCompleter(country_search_names(), self._country_combo)
            country_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            country_completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
            country_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            country_completer.activated[str].connect(self._on_country_completed)
            self._country_combo.setCompleter(country_completer)
            self._country_combo.editTextChanged.connect(self._on_address_edit)
            form.addRow("Land:", self._country_combo)
        else:
            self._address_edit = QPlainTextEdit()
            self._address_edit.setPlaceholderText(
                "FIRMA (optional)\nVOR- UND NACHNAME\nSTRASSE UND HAUSNUMMER\nPLZ ORT\nLAND (English)"
            )
            self._address_edit.setFixedHeight(140)
            self._address_edit.textChanged.connect(self._on_address_edit)
            form.addRow("Lieferadresse:", self._address_edit)

        self._recipient_email = QLineEdit()
        self._recipient_email.setPlaceholderText("office@xeisworks.at")
        form.addRow("Empfänger E-Mail:", self._recipient_email)

        self._status = QLabel("Lade Analyse...")
        self._status.setStyleSheet("color: #64748b;")
        form.addRow("Status:", self._status)

        root.addLayout(form)

        buttons = QDialogButtonBox(self)
        self._send_btn = buttons.addButton("Senden an PLC", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        self._send_btn.clicked.connect(self._send_to_plc)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_context(self) -> None:
        def job() -> _PlcDialogContext:
            order_number = self._summary.wix_order_number()
            address_lines: list[str] = []
            items: list[WixOrderItem] = []
            weight = 0.0
            email = ""
            ref = self._summary.order_reference.strip()
            if ref:
                wix: WixOrdersClient = self._container.resolve(WixOrdersClient)
                if wix.has_credentials():
                    meta = wix.resolve_order_summary(ref)
                    context_method = getattr(wix, "resolve_plc_shipping_context", None)
                    plc_context = context_method(ref) if callable(context_method) else {}
                    order_number = str(meta.get("wix_order_number") or order_number or "").strip()
                    if isinstance(plc_context, dict):
                        order_number = str(plc_context.get("order_number") or order_number).strip()
                        email = str(plc_context.get("email") or "").strip()
                    shipping = str(meta.get("wix_shipping_address") or "").strip()
                    if shipping:
                        address_lines = [ln.strip() for ln in shipping.splitlines() if ln.strip()]
                    if not address_lines:
                        address_lines = wix.resolve_order_address_lines(ref)
                    items = wix.fetch_order_line_items(ref)
                    weight = sum(
                        max(1, int(item.qty or 1))
                        * (float(item.unit_weight_kg or 0) or _DEFAULT_ITEM_WEIGHT_KG)
                        for item in items
                    )
            return _PlcDialogContext(
                order_number=order_number,
                address_lines=address_lines,
                weight_kg=weight,
                items=items,
                email=email,
            )

        self._load_worker = BackgroundWorker(job)
        self._load_worker.signals.result.connect(self._on_context_loaded)
        self._load_worker.signals.error.connect(self._on_context_error)
        self._load_worker.start()

    def _on_context_loaded(self, result: object) -> None:
        if not isinstance(result, _PlcDialogContext):
            self._status.setText("Analyse unvollständig geladen")
            return
        self._context = result
        if result.address_lines and not self._address_edited:
            self._address_edit.blockSignals(True)
            self._address_edit.setPlainText("\n".join(result.address_lines))
            self._address_edit.blockSignals(False)
        if result.weight_kg > 0 and not self._weight_user_set:
            self._weight_edit.setText(f"{result.weight_kg:.2f}".replace(".", ","))
        if result.email and not self._recipient_email.text().strip():
            self._recipient_email.setText(result.email)
        self._sync_product_options()
        self._update_customs_visibility()
        self._status.setText("Bereit")

    def _on_context_error(self, exc: Exception) -> None:
        logger.warning("PLC context load failed: %s", exc)
        self._sync_product_options()
        self._update_customs_visibility()
        self._status.setText(f"Analyse konnte nicht vollständig geladen werden: {exc}")

    def _on_product_selected(self, _value: str) -> None:
        self._product_user_set = True
        self._update_customs_visibility()
        self._update_price()

    def _on_address_edit(self) -> None:
        self._address_edited = True
        if not self._product_user_set:
            self._sync_product_options()
        self._update_customs_visibility()
        self._update_price()

    def _on_weight_edit(self, _value: str) -> None:
        self._weight_user_set = True
        self._update_price()

    def _on_country_completed(self, value: str) -> None:
        self._country_combo.setEditText(country_name_en(value))

    def _current_mode(self) -> str:
        return "LIVE" if self._mode_live.isChecked() else "TEST"

    def _build_reference(self) -> str:
        if self._context.order_number:
            return clean_reference(self._context.order_number)
        contact_name = self._name_edit.text().strip() if self._manual_entry else self._summary.contact_name
        slug = re.sub(r"[^A-Za-z0-9]+", "", contact_name or "")[:12]
        day = time.strftime("%Y%m%d")
        count = self._mail_ref_counters.get(day, 0) + 1
        self._mail_ref_counters[day] = count
        value = f"MAIL-{day}-{count:03d}-{slug}" if slug else f"MAIL-{day}-{count:03d}"
        return clean_reference(value)

    def _current_address_lines(self) -> list[str]:
        if self._manual_entry:
            country = country_name_en(self._country_combo.currentText()).strip()
            return [
                value
                for value in (
                    self._company_edit.text().strip(),
                    self._name_edit.text().strip(),
                    self._street_edit.text().strip(),
                    self._postal_city_edit.text().strip(),
                    country,
                )
                if value
            ]
        return [ln.strip() for ln in self._address_edit.toPlainText().splitlines() if ln.strip()]

    def _parse_address(self, lines: list[str]):
        return parse_shipment_address_lines(
            lines,
            fallback_name=self._summary.contact_name,
            email=self._recipient_email.text().strip(),
            phone="",
        )

    def _country_group(self, iso2: str) -> str:
        code = str(iso2 or "").upper().strip()
        if code == "AT":
            return "AT"
        if code and code in EU_COUNTRIES:
            return "EU"
        return "NON_EU"

    def _current_country(self) -> str:
        return self._parse_address(self._current_address_lines()).country_iso2

    def _update_price(self) -> None:
        product = self._find_product()
        quote = quote_plc_price(
            product_id=product.get("product_id"),
            country_iso2=self._current_country(),
            weight_kg=self._weight_edit.text(),
        )
        if quote is None:
            self._price_label.setText("Preis: —")
            self._price_label.setToolTip("Für diese Kombination ist kein Preis hinterlegt.")
            return
        price = f"{quote.price_eur:.2f}".replace(".", ",")
        self._price_label.setText(f"Preis: {price} €")
        max_weight = f"{quote.max_weight_kg:f}".replace(".", ",")
        self._price_label.setToolTip(f"{quote.tariff_name}, bis {max_weight} kg")

    def _sync_product_options(self) -> None:
        group = self._country_group(self._current_country())
        options = [item for item in self._product_catalog if group in item.get("regions", set())]
        labels = [str(item["label"]) for item in options]
        current = self._product_combo.currentText().strip()
        self._product_combo.blockSignals(True)
        self._product_combo.clear()
        self._product_combo.addItems(labels)
        if labels:
            self._product_combo.setCurrentIndex(labels.index(current) if self._product_user_set and current in labels else 0)
        self._product_combo.blockSignals(False)
        self._update_price()

    def _update_customs_visibility(self) -> None:
        needs_customs = self._country_group(self._current_country()) == "NON_EU"
        self._customs_edit.setVisible(needs_customs)

    def _find_product(self) -> dict:
        label = self._product_combo.currentText().strip()
        for item in self._product_catalog:
            if str(item.get("label") or "").strip() == label:
                return item
        return {}

    def _build_customs_articles(self) -> list[PlcCustomsArticle]:
        out: list[PlcCustomsArticle] = []
        for item in self._context.items:
            qty = max(1, int(item.qty or 1))
            out.append(
                PlcCustomsArticle(
                    sku=str(item.sku or ""),
                    name=str(item.name or item.sku or ""),
                    quantity=qty,
                    net_weight_kg=round(float(item.unit_weight_kg or 0) or _DEFAULT_ITEM_WEIGHT_KG, 3),
                    customs_value_eur=round(float(item.unit_price_gross or 0), 2),
                    currency=str(item.currency or "EUR").upper(),
                )
            )
        return out

    def _send_to_plc(self) -> None:
        if self._manual_entry:
            missing_fields = [
                label
                for label, value in (
                    ("Vor- und Nachname", self._name_edit.text()),
                    ("Straße und Hausnummer", self._street_edit.text()),
                    ("PLZ und Ort", self._postal_city_edit.text()),
                    ("Land", self._country_combo.currentText()),
                )
                if not value.strip()
            ]
            if missing_fields:
                QMessageBox.warning(
                    self,
                    "PLC",
                    "Bitte folgende Empfängerdaten eingeben: " + ", ".join(missing_fields),
                )
                return

        lines = self._current_address_lines()
        if not lines:
            QMessageBox.warning(self, "PLC", "Bitte Lieferadresse eingeben.")
            return

        address = self._parse_address(lines)
        if not address.name1 or not address.city:
            QMessageBox.warning(self, "PLC", "Adresse ist unvollständig.")
            return

        product = self._find_product()
        product_id = str(product.get("product_id") or "").strip()
        pakettyp = str(product.get("pakettyp") or "PC").strip() or "PC"
        if self._country_group(address.country_iso2) == "EU" and product_id != _EU_PRODUCT_ID:
            product_id = _EU_PRODUCT_ID
        if not product_id:
            QMessageBox.warning(self, "PLC", "Versandprodukt ist nicht konfiguriert.")
            return

        weight_raw = self._weight_edit.text().strip().replace(",", ".")
        if not weight_raw:
            QMessageBox.warning(self, "PLC", "Bitte Gewicht angeben.")
            return
        try:
            float(weight_raw)
        except ValueError:
            QMessageBox.warning(self, "PLC", "Gewicht ist ungueltig.")
            return

        ref = self._build_reference()
        invoice_id = self._summary.id or ref
        invoice_number = self._summary.invoice_number or self._summary.id or ref
        articles: list[PlcCustomsArticle] = []
        if self._country_group(address.country_iso2) == "NON_EU":
            articles = self._build_customs_articles()
            if not articles:
                message = (
                    "Für Nicht-EU werden Zollartikel benötigt; deren manuelle Eingabe ist "
                    "in diesem Dialog noch nicht verfügbar."
                    if self._manual_entry
                    else "Für Nicht-EU werden Wix-Positionen benötigt."
                )
                QMessageBox.warning(self, "PLC", message)
                return

        shipment = PlcShipmentDraft(
            reference=ref,
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            mode=self._current_mode(),
            product_id=product_id,
            recipient=address,
            parcels=(PlcParcel(weight_kg=float(weight_raw), package_type=pakettyp, reference=ref),),
            customs_description=self._customs_edit.toPlainText().strip(),
            articles=tuple(articles),
        )
        try:
            shipment.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "PLC", str(exc))
            return

        transport = str(self._transport_combo.currentData() or "webservice")
        self._start_send(shipment, transport)

    def _start_send(self, shipment: PlcShipmentDraft, transport: str) -> None:
        self._send_btn.setEnabled(False)
        self._status.setText("Sende an PLC-Webservice..." if transport == "webservice" else "Erzeuge PLC-Importdatei...")

        def job() -> _PlcSendResult:
            if transport == "webservice":
                secrets: SecretService = self._container.resolve(SecretService)
                settings = webservice_settings_from_secrets(secrets, mode=shipment.mode)
                service: PlcShipmentService = self._container.resolve(PlcShipmentService)
                result = service.submit_webservice(settings, shipment)
                return _PlcSendResult(transport="webservice", reference=shipment.reference, webservice_result=result)

            import_dir = str(
                os.getenv("PLC_IMPORT_DIR" if shipment.mode == "LIVE" else "TEST_PLC_IMPORT_DIR") or ""
            ).strip()
            if not import_dir:
                import_dir = DEFAULT_PLC_IMPORT_DIR if shipment.mode == "LIVE" else DEFAULT_TEST_PLC_IMPORT_DIR
            config = PlcConfig(mode=shipment.mode, import_dir=import_dir)
            path = write_import_file(build_polling_lines(config, shipment), import_dir, f"plc_{shipment.reference}")
            return _PlcSendResult(transport="polling", reference=shipment.reference, polling_path=str(path))

        self._send_worker = BackgroundWorker(job)
        self._send_worker.signals.result.connect(lambda result: self._on_send_result(shipment, result))
        self._send_worker.signals.error.connect(lambda exc: self._on_send_error(shipment, exc))
        self._send_worker.signals.finished.connect(lambda: self._send_btn.setEnabled(True))
        self._send_worker.start()

    def _on_send_result(self, shipment: PlcShipmentDraft, result: object) -> None:
        if not isinstance(result, _PlcSendResult):
            self._on_send_error(shipment, RuntimeError("PLC lieferte ein ungültiges Ergebnis"))
            return
        if result.transport == "polling":
            self._status.setText(f"Importdatei abgelegt: {result.polling_path}")
            QMessageBox.information(
                self,
                "PLC-Dateiimport",
                "Die Importdatei wurde abgelegt. Ondot Data Exchange verarbeitet sie zeitversetzt; "
                "dies ist der explizite Fallback, nicht der direkte Druck.",
            )
            self.accept()
            return

        if result.webservice_result is None:
            self._on_send_error(shipment, RuntimeError("PLC-Webservice lieferte kein Label"))
            return
        try:
            archive_path = self._label_archive.save(shipment, result.webservice_result.pdf_bytes)
            job_id = self._queue_webservice_label(archive_path, shipment.reference)
            service: PlcShipmentService = self._container.resolve(PlcShipmentService)
            service.mark_print_queued(shipment, job_id)
        except Exception as exc:  # noqa: BLE001 - shipment was created; preserve the recovery message.
            self._status.setText("PLC-Sendung erstellt, Druckauftrag fehlgeschlagen")
            QMessageBox.warning(
                self,
                "PLC-Label erstellt",
                "Die Sendung wurde von PLC erstellt, aber der lokale Druckauftrag konnte nicht eingereiht werden.\n\n"
                f"Details: {exc}",
            )
            return

        tracking = ", ".join(result.webservice_result.tracking_codes) or "ohne Trackingcode"
        self._status.setText(f"PLC-Label archiviert; Druckauftrag {job_id[:8]}…")
        QMessageBox.information(
            self,
            "PLC-Label",
            "Label direkt erstellt, vor dem Druck archiviert und zum Druck eingereiht.\n"
            f"Tracking: {tracking}\n"
            f"Archiv: {archive_path}",
        )
        self.accept()

    def _on_send_error(self, shipment: PlcShipmentDraft, exc: Exception) -> None:
        if isinstance(exc, PlcDuplicateShipmentError):
            archive_path = self._label_archive.find(shipment)
            if archive_path is not None:
                self._handle_duplicate_archived_label(shipment, archive_path)
                return

            self._status.setText("PLC-Sendung besteht bereits; kein lokales Archiv-PDF vorhanden")
            QMessageBox.warning(
                self,
                "PLC-Label bereits erstellt",
                "PLC sperrt eine zweite Erstellung dieser Sendung. Ein lokales Archiv-PDF wurde noch nicht gefunden, "
                "daher kann XW-Studio keinen sicheren Nachdruck ausführen.",
            )
            return

        logger.warning("PLC send failed invoice=%s: %s", self._summary.id, exc)
        self._status.setText(f"PLC-Fehler: {exc}")
        QMessageBox.critical(self, "PLC Fehler", str(exc))

    def _handle_duplicate_archived_label(
        self,
        shipment: PlcShipmentDraft,
        archive_path: object,
    ) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("PLC-Label bereits gedruckt")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("PLC-Label bereits gedruckt.")
        box.setInformativeText(
            "Archiviertes Label öffnen oder neues Label mit Suffix -2 erstellen?\n\n"
            f"Archiv: {archive_path}"
        )
        open_btn = box.addButton("Archiv-PDF öffnen", QMessageBox.ButtonRole.AcceptRole)
        additional_btn = box.addButton("Neues Label erstellen", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(open_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(archive_path)))
            self._status.setText("Archiviertes PLC-Label geöffnet")
            self.accept()
            return
        if clicked is additional_btn:
            next_shipment = self._next_additional_shipment(shipment)
            self._status.setText(
                "Erzeuge weiteres PLC-Label mit Referenz "
                f"{next_shipment.reference} / {next_shipment.invoice_number}"
            )
            self._start_send(next_shipment, "webservice")

    def _next_additional_shipment(self, shipment: PlcShipmentDraft) -> PlcShipmentDraft:
        for index in range(2, 100):
            suffix = str(index)
            reference = self._append_reference_suffix(shipment.reference, suffix)
            invoice_number = self._append_reference_suffix(shipment.invoice_number, suffix)
            parcels = tuple(
                replace(parcel, reference=self._append_reference_suffix(parcel.reference or shipment.reference, suffix))
                for parcel in shipment.parcels
            )
            candidate = replace(
                shipment,
                reference=reference,
                invoice_number=invoice_number,
                parcels=parcels,
            )
            if self._label_archive.find(candidate) is None:
                return candidate
        raise RuntimeError("Kein freier PLC-Label-Suffix zwischen -2 und -99 gefunden.")

    @staticmethod
    def _append_reference_suffix(value: object, suffix: str) -> str:
        cleaned = clean_reference(value)
        match = re.search(r"-(\d{1,2})$", cleaned)
        if match and 2 <= int(match.group(1)) <= 99:
            cleaned = cleaned[:match.start()]
        base = cleaned.strip(" -")
        next_value = f"{base}-{suffix}" if base else suffix
        return clean_reference(next_value)

    def _queue_webservice_label(self, pdf_path: str | os.PathLike[str], reference: str) -> str:
        printer = self._resolve_plc_printer()
        if not printer:
            raise RuntimeError("PLC-Labeldrucker ist nicht konfiguriert")
        if not os.path.isfile(pdf_path):
            raise RuntimeError(f"Archiviertes PLC-PDF fehlt: {pdf_path}")
        queue: PrintQueueService = self._container.resolve(PrintQueueService)
        profile = self._container.config.printing.resolve_profile("plc_label")
        return queue.enqueue(
            PdfPrintJob(
                pdf_path=os.fspath(pdf_path),
                printer_name=printer,
                copies=1,
                job_kind="label",
                description=f"PLC-Label {reference}",
                page_size=str(getattr(profile, "page_size", "") or "A5"),
                orientation=str(getattr(profile, "orientation", "") or "portrait"),
                placement_mode=str(getattr(profile, "placement_mode", "") or "printable_origin"),  # type: ignore[arg-type]
                scale_mode=str(getattr(profile, "scale_mode", "") or "fit"),  # type: ignore[arg-type]
                alignment=str(getattr(profile, "alignment", "") or "center"),  # type: ignore[arg-type]
                dpi=int(profile.dpi) if profile is not None and profile.dpi else None,
                x_offset_mm=float(getattr(profile, "x_offset_mm", 0.0) or 0.0),
                y_offset_mm=float(getattr(profile, "y_offset_mm", 0.0) or 0.0),
                # Preserve the exact PLC response for safe local reprints.
                cleanup_paths=(),
            )
        )

    def _resolve_plc_printer(self) -> str:
        secrets: SecretService = self._container.resolve(SecretService)
        configured = secrets.get_secret("PLC_LABEL_PRINTER").strip()
        if configured:
            return configured
        profile = self._container.config.printing.resolve_profile("plc_label")
        if profile is None:
            profile = self._container.config.printing.resolve_profile("label")
        if profile is not None and profile.printer_name.strip():
            return profile.printer_name.strip()
        return str(self._container.config.printing.label_printer or "").strip()

    @staticmethod
    def _load_products() -> list[dict]:
        defaults = {
            "Paket Oesterreich": {"product_id": os.getenv("PLC_PRODUCT_ID_PAKET_OESTERREICH", "10")},
            "Premium Int. Outbound B2B": {"product_id": os.getenv("PLC_PRODUCT_ID_PREMIUM_INT_OUTBOUND_B2B", "45")},
            "Paket Plus Int. Outbound": {"product_id": os.getenv("PLC_PRODUCT_ID_PAKET_PLUS_INT_OUTBOUND", "70")},
        }
        raw = os.getenv("PLC_PRODUCTS_JSON")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        label = str(item.get("label") or "").strip()
                        pid = str(item.get("product_id") or "").strip()
                        pakettyp = str(item.get("pakettyp") or "").strip() or "PC"
                        if label in defaults and pid:
                            defaults[label]["product_id"] = pid
                            defaults[label]["pakettyp"] = pakettyp
            except Exception:
                pass
        return [
            {
                "label": "Paket Oesterreich",
                "product_id": defaults["Paket Oesterreich"]["product_id"],
                "pakettyp": defaults["Paket Oesterreich"].get("pakettyp", "PC"),
                "regions": {"AT"},
            },
            {
                "label": "Premium Int. Outbound B2B",
                "product_id": defaults["Premium Int. Outbound B2B"]["product_id"],
                "pakettyp": defaults["Premium Int. Outbound B2B"].get("pakettyp", "PC"),
                "regions": {"EU"},
            },
            {
                "label": "Paket Plus Int. Outbound",
                "product_id": defaults["Paket Plus Int. Outbound"]["product_id"],
                "pakettyp": defaults["Paket Plus Int. Outbound"].get("pakettyp", "PC"),
                "regions": {"EU", "NON_EU"},
            },
        ]
