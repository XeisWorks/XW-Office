"""PLC label export dialog (ported from legacy Tkinter flow)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.plc.polling import (
    DEFAULT_PLC_IMPORT_DIR,
    DEFAULT_TEST_PLC_IMPORT_DIR,
    PlcConfig,
    write_import_file,
)
from xw_office.services.plc.models import (
    PlcCustomsArticle,
    PlcParcel,
    PlcShipmentDraft,
    build_polling_lines,
    clean_reference,
    parse_shipment_address_lines,
    requires_customs_declaration,
)
from xw_office.services.plc.pricing import quote_plc_price
from xw_office.services.plc.customs_document import ensure_customs_a5_print_file
from xw_office.services.plc.label_archive import PlcLabelArchive
from xw_office.services.plc.service import PlcDuplicateShipmentError, PlcShipmentService
from xw_office.services.plc.webservice import PlcWebserviceResult, webservice_settings_from_secrets
from xw_office.services.printing.print_jobs import PdfPrintJob
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.secrets.service import SecretService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.shipping.countries import (
    country_name_en,
    country_names_en,
    country_search_names,
)
from xw_office.services.wix.client import WixOrderItem, WixOrdersClient

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_EU_PRODUCT_ID = "45"
_CUSTOMS_DESCRIPTION = "Printed sheet music books"
_CUSTOMS_ARTICLE_NAME = "Printed sheet music book"
_CUSTOMS_ORIGIN_ISO2 = "AT"
_CUSTOMS_HS_TARIFF = "49040000"
_SUCCESS_OVERLAY_MS = 700


def queue_archived_plc_label(
    container: Container,
    pdf_path: str | os.PathLike[str],
    reference: str,
) -> str:
    """Queue an already archived PLC label without contacting PLC again."""
    secrets: SecretService = container.resolve(SecretService)
    printer = secrets.get_secret("PLC_LABEL_PRINTER").strip()
    profile = container.config.printing.resolve_profile("plc_label")
    if not printer and profile is None:
        profile = container.config.printing.resolve_profile("label")
    if not printer and profile is not None:
        printer = profile.printer_name.strip()
    if not printer:
        printer = str(container.config.printing.label_printer or "").strip()
    if not printer:
        raise RuntimeError("PLC-Labeldrucker ist nicht konfiguriert")
    if not os.path.isfile(pdf_path):
        raise RuntimeError(f"Archiviertes PLC-PDF fehlt: {pdf_path}")
    queue: PrintQueueService = container.resolve(PrintQueueService)
    return queue.enqueue(
        PdfPrintJob(
            pdf_path=os.fspath(pdf_path),
            printer_name=printer,
            copies=1,
            job_kind="label",
            description=f"PLC-Label {reference}",
            page_size=str(getattr(profile, "page_size", "") or "A5"),
            orientation=str(getattr(profile, "orientation", "") or "portrait"),
            placement_mode=str(getattr(profile, "placement_mode", "") or "paper_origin"),  # type: ignore[arg-type]
            scale_mode=str(getattr(profile, "scale_mode", "") or "none"),  # type: ignore[arg-type]
            alignment=str(getattr(profile, "alignment", "") or "center"),  # type: ignore[arg-type]
            dpi=int(profile.dpi) if profile is not None and profile.dpi else None,
            x_offset_mm=float(getattr(profile, "x_offset_mm", 0.0) or 0.0),
            y_offset_mm=float(getattr(profile, "y_offset_mm", 0.0) or 0.0),
            cleanup_paths=(),
        )
    )


def queue_archived_plc_customs(
    container: Container,
    pdf_path: str | os.PathLike[str],
    reference: str,
) -> str:
    """Queue the persistent AF/A5 derivative of an archived PLC customs PDF."""
    profile = container.config.printing.resolve_profile("plc_customs")
    printer = str(getattr(profile, "printer_name", "") or "Zollformular XW 100").strip()
    if not printer:
        raise RuntimeError("Drucker 'Zollformular XW 100' ist nicht konfiguriert")
    if not os.path.isfile(pdf_path):
        raise RuntimeError(f"Archiviertes PLC-Zollformular fehlt: {pdf_path}")
    print_path = ensure_customs_a5_print_file(pdf_path)
    queue: PrintQueueService = container.resolve(PrintQueueService)
    return queue.enqueue(
        PdfPrintJob(
            pdf_path=os.fspath(print_path),
            printer_name=printer,
            copies=1,
            job_kind="invoice",
            description=f"Zollformular {reference}",
            page_size=str(getattr(profile, "page_size", "") or "A5"),
            orientation=str(getattr(profile, "orientation", "") or "portrait"),
            placement_mode=str(getattr(profile, "placement_mode", "") or "paper_origin"),  # type: ignore[arg-type]
            scale_mode=str(getattr(profile, "scale_mode", "") or "fit"),  # type: ignore[arg-type]
            scale_percent=float(getattr(profile, "scale_percent", 100.0) or 100.0),
            alignment=str(getattr(profile, "alignment", "") or "top_left"),  # type: ignore[arg-type]
            dpi=int(profile.dpi) if profile is not None and profile.dpi else None,
            x_offset_mm=float(getattr(profile, "x_offset_mm", 0.0) or 0.0),
            y_offset_mm=float(getattr(profile, "y_offset_mm", 0.0) or 0.0),
            cleanup_paths=(),
        )
    )


@dataclass
class _PlcDialogContext:
    order_number: str
    address_lines: list[str]
    weight_kg: float
    items: list[WixOrderItem]
    email: str = ""
    phone: str = ""
    source: str = "wix"


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
        self._success_overlay: QFrame | None = None

        self.setWindowTitle("PLC Label Print")
        self.setMinimumWidth(960)
        self.resize(1180, 680)
        self._build_ui()
        if self._manual_entry:
            # Header "PLC-Label" button: no invoice/customer context, so the
            # office mailbox is the correct default recipient.
            self._recipient_email.setText(str(recipient_email or "office@xeisworks.at").strip())
        else:
            # Invoice-linked PLC send: leave blank if not yet resolved so the
            # customer's email (from cache or _load_context below) fills it in
            # instead of falling back to the office mailbox.
            self._recipient_email.setText(str(recipient_email or "").strip())
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
            self._status.setText("Fenster bereit – Wix-Cache wird im Hintergrund gelesen …")
            # Let the dialog paint before cache I/O or a possible Wix request
            # starts. This keeps opening the popup independent of network speed.
            QTimer.singleShot(0, self._load_context)

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
        self._customs_edit.setPlaceholderText(_CUSTOMS_DESCRIPTION)
        self._customs_edit.setFixedHeight(72)

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

        self._recipient_phone = QLineEdit()
        self._recipient_phone.setPlaceholderText("Aus Wix, falls vorhanden")
        form.addRow("Empfänger Telefon:", self._recipient_phone)

        self._status = QLabel("Lade Analyse...")
        self._status.setStyleSheet("color: #64748b;")
        form.addRow("Status:", self._status)

        root.addLayout(form)

        self._customs_group = QGroupBox("Zollerklärung (CN23)")
        customs_layout = QVBoxLayout(self._customs_group)
        customs_hint = QLabel(
            "Das manuell korrigierte Paketgewicht ist das Bruttogewicht. Wix liefert automatisch "
            "Anzahl, Einzelpreis und grobes Nettogewicht je Produkt; Einzelgewichte können in den "
            "Artikeldetails korrigiert werden."
        )
        customs_hint.setWordWrap(True)
        customs_hint.setStyleSheet("color: #64748b;")
        customs_layout.addWidget(customs_hint)
        customs_form = QFormLayout()
        customs_form.addRow("Inhaltsangabe (Englisch):", self._customs_edit)
        customs_layout.addLayout(customs_form)

        self._customs_summary = QLabel("Noch keine Zollartikel geladen")
        self._customs_summary.setWordWrap(True)
        self._customs_summary.setStyleSheet("font-weight: 600;")
        customs_layout.addWidget(self._customs_summary)

        self._customs_details_btn = QPushButton("Artikeldetails anzeigen")
        self._customs_details_btn.setCheckable(True)
        self._customs_details_btn.toggled.connect(self._set_customs_details_visible)
        customs_layout.addWidget(self._customs_details_btn)

        self._customs_details = QWidget(self._customs_group)
        details_layout = QVBoxLayout(self._customs_details)
        details_layout.setContentsMargins(0, 0, 0, 0)

        self._customs_table = QTableWidget(0, 8, self._customs_details)
        self._customs_table.setHorizontalHeaderLabels(
            ["Artikel (Englisch)", "SKU", "Anzahl", "Netto kg/Stk", "Wert/Stk", "Währung", "Ursprung", "Zolltarif-Nr."]
        )
        self._customs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._customs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._customs_table.setMinimumHeight(190)
        self._customs_table.verticalHeader().setVisible(False)
        header = self._customs_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._customs_table.itemChanged.connect(self._update_customs_summary)
        details_layout.addWidget(self._customs_table)

        customs_buttons = QHBoxLayout()
        add_customs = QPushButton("Artikel hinzufügen")
        remove_customs = QPushButton("Ausgewählten Artikel entfernen")
        add_customs.clicked.connect(self._add_empty_customs_row)
        remove_customs.clicked.connect(self._remove_selected_customs_row)
        customs_buttons.addWidget(add_customs)
        customs_buttons.addWidget(remove_customs)
        customs_buttons.addStretch()
        details_layout.addLayout(customs_buttons)
        customs_layout.addWidget(self._customs_details)
        self._set_customs_details_visible(False)
        root.addWidget(self._customs_group)
        self._customs_group.setVisible(False)

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
            phone = ""
            ref = self._summary.order_reference.strip()
            if ref:
                wix: WixOrdersClient = self._container.resolve(WixOrdersClient)
                if wix.has_credentials():
                    cached_method = getattr(wix, "get_cached_plc_order_context", None)
                    cached = cached_method(ref) if callable(cached_method) else None
                    source = "cache" if isinstance(cached, dict) else "wix"
                    if isinstance(cached, dict):
                        meta = cached.get("meta") if isinstance(cached.get("meta"), dict) else {}
                        plc_context = (
                            cached.get("shipping")
                            if isinstance(cached.get("shipping"), dict)
                            else {}
                        )
                        cached_items = cached.get("items")
                        items = list(cached_items) if isinstance(cached_items, list) else []
                    else:
                        meta = wix.resolve_order_summary(ref)
                        context_method = getattr(wix, "resolve_plc_shipping_context", None)
                        plc_context = context_method(ref) if callable(context_method) else {}
                        items = wix.fetch_order_line_items(ref)
                    order_number = str(meta.get("wix_order_number") or order_number or "").strip()
                    if isinstance(plc_context, dict):
                        order_number = str(plc_context.get("order_number") or order_number).strip()
                        email = str(plc_context.get("email") or "").strip()
                        phone = str(plc_context.get("phone") or "").strip()
                    shipping = str(meta.get("wix_shipping_address") or "").strip()
                    if shipping:
                        address_lines = [ln.strip() for ln in shipping.splitlines() if ln.strip()]
                    if not address_lines and source != "cache":
                        address_lines = wix.resolve_order_address_lines(ref)
                    weight = sum(
                        max(1, int(item.qty or 1))
                        * float(item.unit_weight_kg or 0)
                        for item in items
                        if not item.is_digital
                    )
                else:
                    source = "none"
            else:
                source = "none"
            return _PlcDialogContext(
                order_number=order_number,
                address_lines=address_lines,
                weight_kg=weight,
                items=items,
                email=email,
                phone=phone,
                source=source,
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
        if result.phone and not self._recipient_phone.text().strip():
            self._recipient_phone.setText(result.phone)
        self._populate_customs_table(result.items)
        self._sync_product_options()
        self._update_customs_visibility()
        physical_count = sum(max(1, int(item.qty or 1)) for item in result.items if not item.is_digital)
        source_label = "Wix-Cache" if result.source == "cache" else "Wix"
        self._status.setText(
            f"Bereit ({source_label}) – {physical_count} physische Notenhefte; Paketgewicht/Verpackung prüfen"
            if physical_count
            else f"Bereit ({source_label}) – keine physischen Wix-Positionen gefunden"
        )

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
        self._update_customs_summary()

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
            phone=self._recipient_phone.text().strip(),
        )

    def _country_group(self, iso2: str, *, postal_code: str = "", city: str = "") -> str:
        code = str(iso2 or "").upper().strip()
        if code == "AT":
            return "AT"
        if code and not requires_customs_declaration(code, postal_code=postal_code, city=city):
            return "EU"
        return "NON_EU"

    def _current_country(self) -> str:
        return self._parse_address(self._current_address_lines()).country_iso2

    def _current_country_group(self) -> str:
        address = self._parse_address(self._current_address_lines())
        return self._country_group(
            address.country_iso2,
            postal_code=address.zip,
            city=address.city,
        )

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
        group = self._current_country_group()
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
        needs_customs = self._current_country_group() == "NON_EU"
        self._customs_group.setVisible(needs_customs)
        self._send_btn.setText(
            "PLC-Marke + Zollformular drucken" if needs_customs else "PLC-Marke drucken"
        )
        if needs_customs and not self._customs_edit.toPlainText().strip():
            self._customs_edit.setPlainText(_CUSTOMS_DESCRIPTION)
        if needs_customs and self._manual_entry and self._customs_table.rowCount() == 0:
            self._add_empty_customs_row()

    def _find_product(self) -> dict:
        label = self._product_combo.currentText().strip()
        for item in self._product_catalog:
            if str(item.get("label") or "").strip() == label:
                return item
        return {}

    @staticmethod
    def _customs_cell(value: object) -> QTableWidgetItem:
        return QTableWidgetItem(str(value or ""))

    def _append_customs_row(
        self,
        *,
        name: str = _CUSTOMS_ARTICLE_NAME,
        sku: str = "",
        quantity: int = 1,
        weight_kg: float = 0.0,
        value: float = 0.0,
        currency: str = "EUR",
        origin: str = _CUSTOMS_ORIGIN_ISO2,
        tariff: str = _CUSTOMS_HS_TARIFF,
    ) -> None:
        row = self._customs_table.rowCount()
        self._customs_table.insertRow(row)
        values = (
            name,
            sku,
            str(max(int(quantity or 1), 1)),
            f"{weight_kg:.3f}" if weight_kg > 0 else "",
            f"{value:.2f}" if value > 0 else "",
            currency,
            origin,
            tariff,
        )
        for column, value_text in enumerate(values):
            self._customs_table.setItem(row, column, self._customs_cell(value_text))

    def _populate_customs_table(self, items: list[WixOrderItem]) -> None:
        self._customs_table.blockSignals(True)
        self._customs_table.setRowCount(0)
        for item in items:
            if item.is_digital:
                continue
            title = str(item.name or "").strip()
            description = _CUSTOMS_ARTICLE_NAME
            if title and title.casefold() != _CUSTOMS_ARTICLE_NAME.casefold():
                description = f"{_CUSTOMS_ARTICLE_NAME} - {title}"[:100]
            self._append_customs_row(
                name=description,
                sku=str(item.sku or ""),
                quantity=max(1, int(item.qty or 1)),
                weight_kg=float(item.unit_weight_kg or 0),
                value=float(item.unit_price_gross or 0),
                currency=str(item.currency or "EUR").upper(),
            )
        self._customs_table.blockSignals(False)
        self._update_customs_summary()
        self._set_customs_details_visible(not self._customs_rows_complete())

    def _add_empty_customs_row(self) -> None:
        self._append_customs_row()
        self._update_customs_summary()
        self._set_customs_details_visible(True)

    def _remove_selected_customs_row(self) -> None:
        row = self._customs_table.currentRow()
        if row >= 0:
            self._customs_table.removeRow(row)
        self._update_customs_summary()

    def _customs_text(self, row: int, column: int) -> str:
        cell = self._customs_table.item(row, column)
        return str(cell.text() if cell is not None else "").strip()

    def _set_customs_details_visible(self, visible: bool) -> None:
        expanded = bool(visible)
        self._customs_details.setVisible(expanded)
        self._customs_details_btn.blockSignals(True)
        self._customs_details_btn.setChecked(expanded)
        self._customs_details_btn.setText(
            "Artikeldetails ausblenden" if expanded else "Artikeldetails anzeigen"
        )
        self._customs_details_btn.blockSignals(False)

    def _customs_rows_complete(self) -> bool:
        if self._customs_table.rowCount() == 0:
            return False
        for row in range(self._customs_table.rowCount()):
            if not all(self._customs_text(row, column) for column in (0, 2, 3, 4, 5, 6, 7)):
                return False
            try:
                qty = int(self._customs_text(row, 2))
                weight = float(self._customs_text(row, 3).replace(",", "."))
                value = float(self._customs_text(row, 4).replace(",", "."))
            except ValueError:
                return False
            if qty <= 0 or weight <= 0 or value <= 0:
                return False
        return True

    def _gross_weight_kg(self) -> float | None:
        try:
            value = float(self._weight_edit.text().strip().replace(",", "."))
        except ValueError:
            return None
        return value if value > 0 else None

    def _update_customs_summary(self, _item: object = None) -> None:
        quantity = 0
        net_weight = 0.0
        customs_value = 0.0
        currencies: set[str] = set()
        incomplete = 1 if self._customs_table.rowCount() == 0 else 0
        for row in range(self._customs_table.rowCount()):
            try:
                qty = int(self._customs_text(row, 2))
                weight = float(self._customs_text(row, 3).replace(",", "."))
                value = float(self._customs_text(row, 4).replace(",", "."))
            except ValueError:
                incomplete += 1
                continue
            quantity += max(qty, 0)
            net_weight += max(qty, 0) * max(weight, 0.0)
            customs_value += max(qty, 0) * max(value, 0.0)
            currency = self._customs_text(row, 5).upper()
            if currency:
                currencies.add(currency)
            if (
                qty <= 0
                or weight <= 0
                or value <= 0
                or not all(self._customs_text(row, column) for column in (0, 2, 3, 4, 5, 6, 7))
            ):
                incomplete += 1
        currency_label = (
            next(iter(currencies))
            if len(currencies) == 1
            else "EUR"
            if not currencies
            else "gemischte Währung"
        )
        gross_weight = self._gross_weight_kg()
        summary = f"{quantity} Stk. · Zoll-Netto {net_weight:.3f} kg"
        if gross_weight is not None:
            packaging_weight = gross_weight - net_weight
            summary += (
                f" · Paket-Brutto {gross_weight:.3f} kg"
                f" · Verpackung/Differenz {packaging_weight:.3f} kg"
            )
        else:
            packaging_weight = None
            summary += " · Paket-Brutto fehlt"
        summary += f" · Warenwert {customs_value:.2f} {currency_label}"
        if incomplete:
            summary += f" · {incomplete} Zeile(n) unvollständig"
            self._customs_summary.setStyleSheet("font-weight: 600; color: #b45309;")
        elif packaging_weight is None:
            self._customs_summary.setStyleSheet("font-weight: 600; color: #b45309;")
        elif packaging_weight < -0.001:
            summary += " · Zoll-Netto ist höher als Paket-Brutto – Gewichte prüfen"
            self._customs_summary.setStyleSheet("font-weight: 600; color: #b91c1c;")
        else:
            self._customs_summary.setStyleSheet("font-weight: 600; color: #0f766e;")
        self._customs_summary.setText(summary)

    def _build_customs_articles(self) -> list[PlcCustomsArticle]:
        out: list[PlcCustomsArticle] = []
        for row in range(self._customs_table.rowCount()):
            try:
                qty = int(self._customs_text(row, 2))
                weight = float(self._customs_text(row, 3).replace(",", "."))
                value = float(self._customs_text(row, 4).replace(",", "."))
            except ValueError as exc:
                raise ValueError(f"Zollartikel {row + 1}: Anzahl, Gewicht oder Wert ist ungültig") from exc
            out.append(
                PlcCustomsArticle(
                    sku=self._customs_text(row, 1),
                    name=self._customs_text(row, 0)[:100],
                    quantity=qty,
                    net_weight_kg=round(weight, 3),
                    customs_value_eur=round(value, 2),
                    currency=self._customs_text(row, 5).upper(),
                    origin_iso2=self._customs_text(row, 6).upper(),
                    hs_tariff_number=self._customs_text(row, 7),
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
        address_group = self._country_group(
            address.country_iso2,
            postal_code=address.zip,
            city=address.city,
        )
        if address_group == "EU" and product_id != _EU_PRODUCT_ID:
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
        if address_group == "NON_EU":
            try:
                articles = self._build_customs_articles()
            except ValueError as exc:
                QMessageBox.warning(self, "PLC", str(exc))
                return
            if not articles:
                QMessageBox.warning(self, "PLC", "Für dieses Zielland wird mindestens ein Zollartikel benötigt.")
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
            self._show_success_overlay("Importdatei erstellt")
            return

        if result.webservice_result is None:
            self._on_send_error(shipment, RuntimeError("PLC-Webservice lieferte kein Label"))
            return
        archive_path = None
        customs_path = None
        customs_print_path = None
        job_id = ""
        customs_job_id = ""
        try:
            customs_pdf = result.webservice_result.shipment_documents
            if shipment.country_group == "NON_EU" and not customs_pdf:
                raise RuntimeError(
                    "PLC hat trotz angeforderter Zollerklärung kein CN23-PDF zurückgegeben. "
                    "Es wurde noch kein Druckauftrag gestartet."
                )

            # Both remote responses must be safe locally before either print
            # job starts. Printer/profile errors can then be retried without
            # creating another PLC shipment.
            archive_path = self._label_archive.save(shipment, result.webservice_result.pdf_bytes)
            if shipment.country_group == "NON_EU":
                customs_path = self._label_archive.save_customs_document(shipment, customs_pdf)
                customs_print_path = self._label_archive.ensure_customs_print_document(shipment)

            job_id = self._queue_webservice_label(archive_path, shipment.reference)
            service: PlcShipmentService = self._container.resolve(PlcShipmentService)
            service.mark_print_queued(shipment, job_id)
            if customs_print_path is not None:
                customs_job_id = self._queue_customs_document(customs_print_path, shipment.reference)
        except Exception as exc:  # noqa: BLE001 - shipment was created; preserve the recovery message.
            self._status.setText("PLC-Sendung erstellt, Druckauftrag fehlgeschlagen")
            archived = "\n".join(
                f"- {path}"
                for path in (archive_path, customs_path, customs_print_path)
                if path is not None
            )
            archive_note = (
                f"\n\nLokal archiviert:\n{archived}"
                if archived
                else "\n\nDie gelieferten PDFs konnten nicht vollständig lokal archiviert werden."
            )
            QMessageBox.warning(
                self,
                "PLC-Label erstellt",
                "Die Sendung wurde von PLC erstellt, aber mindestens ein lokaler Druckauftrag "
                "konnte nicht eingereiht werden."
                f"{archive_note}\n\nDetails: {exc}",
            )
            return

        tracking = ", ".join(result.webservice_result.tracking_codes) or "ohne Trackingcode"
        if customs_job_id:
            self._status.setText(
                f"PLC-Label und Zollformular archiviert; Druckaufträge {job_id[:8]}… / {customs_job_id[:8]}…"
            )
        else:
            self._status.setText(f"PLC-Label archiviert; Druckauftrag {job_id[:8]}…")
        logger.info(
            "PLC label created reference=%s tracking=%s archive=%s print_job=%s "
            "customs_archive=%s customs_print_archive=%s customs_job=%s",
            shipment.reference,
            tracking,
            archive_path,
            job_id,
            customs_path,
            customs_print_path,
            customs_job_id,
        )
        self._show_success_overlay(
            "PLC-Label + Zollformular erstellt" if customs_job_id else "PLC-Label erstellt"
        )

    def _show_success_overlay(self, message: str) -> None:
        if self._success_overlay is not None:
            self._success_overlay.deleteLater()

        overlay = QFrame(self)
        overlay.setObjectName("plcSuccessOverlay")
        overlay.setGeometry(self.rect())
        overlay.setStyleSheet(
            "QFrame#plcSuccessOverlay {"
            "background-color: rgba(15, 23, 42, 220);"
            "border-radius: 10px;"
            "}"
            "QFrame#plcSuccessCard {"
            "background-color: #f8fafc;"
            "border: 2px solid #22c55e;"
            "border-radius: 16px;"
            "}"
            "QLabel#plcSuccessCheck {"
            "background-color: #16a34a;"
            "color: white;"
            "border-radius: 42px;"
            "font-size: 52px;"
            "font-weight: bold;"
            "}"
            "QLabel#plcSuccessText {"
            "color: #14532d;"
            "font-size: 17px;"
            "font-weight: bold;"
            "}"
        )
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.addStretch()
        card = QFrame(overlay)
        card.setObjectName("plcSuccessCard")
        card.setFixedSize(240, 170)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 18)
        check = QLabel("✓", card)
        check.setObjectName("plcSuccessCheck")
        check.setFixedSize(84, 84)
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(check, alignment=Qt.AlignmentFlag.AlignCenter)
        text = QLabel(message, card)
        text.setObjectName("plcSuccessText")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(text)
        overlay_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addStretch()

        self._success_overlay = overlay
        overlay.raise_()
        overlay.show()
        QTimer.singleShot(_SUCCESS_OVERLAY_MS, self.accept)

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
                "daher kann XW-Office keinen sicheren Nachdruck ausführen.",
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
        customs_path = self._label_archive.find_customs_document(shipment)
        customs_print_path = self._label_archive.find_customs_print_document(shipment)
        if customs_path is not None and customs_print_path is None:
            try:
                customs_print_path = self._label_archive.ensure_customs_print_document(shipment)
            except Exception as exc:  # noqa: BLE001 - the PLC original remains available.
                logger.warning("Archived customs A5 preparation failed path=%s: %s", customs_path, exc)
        box.setWindowTitle("PLC-Sendung bereits erstellt")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Für diese Sendung existieren bereits lokale PLC-Dokumente.")
        archive_lines = [f"Label: {archive_path}"]
        if customs_path is not None:
            archive_lines.append(f"Zollformular (PLC-Original): {customs_path}")
        if customs_print_path is not None:
            archive_lines.append(f"Zollformular (A5-Druck): {customs_print_path}")
        box.setInformativeText(
            "Die archivierten PDFs können ohne neue PLC-Sendung erneut gedruckt werden.\n\n"
            + "\n".join(archive_lines)
        )
        reprint_label = "Beide PDFs erneut drucken" if customs_path is not None else "Label erneut drucken"
        reprint_btn = box.addButton(reprint_label, QMessageBox.ButtonRole.AcceptRole)
        open_btn = box.addButton("Label-PDF öffnen", QMessageBox.ButtonRole.ActionRole)
        customs_open_btn = None
        customs_print_open_btn = None
        if customs_path is not None:
            customs_open_btn = box.addButton("Zoll-Original öffnen", QMessageBox.ButtonRole.ActionRole)
        if customs_print_path is not None:
            customs_print_open_btn = box.addButton("Zoll-A5 öffnen", QMessageBox.ButtonRole.ActionRole)
        additional_btn = box.addButton("Neues Label erstellen", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(reprint_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reprint_btn:
            try:
                label_job_id = self._queue_webservice_label(archive_path, shipment.reference)
                customs_job_id = ""
                if customs_path is not None:
                    customs_job_id = self._queue_customs_document(
                        customs_print_path or customs_path,
                        shipment.reference,
                    )
            except Exception as exc:  # noqa: BLE001 - keep the archived recovery path visible.
                QMessageBox.warning(self, "PLC-Nachdruck", f"Nachdruck konnte nicht eingereiht werden:\n\n{exc}")
                return
            jobs = label_job_id[:8] + "…"
            if customs_job_id:
                jobs += " / " + customs_job_id[:8] + "…"
            self._status.setText(f"Archivierter PLC-Nachdruck eingereiht: {jobs}")
            self._show_success_overlay("PLC-Dokumente erneut eingereiht")
            return
        if clicked is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(archive_path)))
            self._status.setText("Archiviertes PLC-Label geöffnet")
            return
        if customs_open_btn is not None and clicked is customs_open_btn and customs_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(customs_path)))
            self._status.setText("Archiviertes PLC-Zolloriginal geöffnet")
            return
        if (
            customs_print_open_btn is not None
            and clicked is customs_print_open_btn
            and customs_print_path is not None
        ):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(customs_print_path)))
            self._status.setText("Archivierte A5-Druckfassung geöffnet")
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
        return queue_archived_plc_label(self._container, pdf_path, reference)

    def _queue_customs_document(self, pdf_path: str | os.PathLike[str], reference: str) -> str:
        return queue_archived_plc_customs(self._container, pdf_path, reference)

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
