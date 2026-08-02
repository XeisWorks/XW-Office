"""App-wide settings — DB status, secrets overview, printer config."""
from __future__ import annotations

import html
import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.signals import AppSignals
from xw_office.core.worker import BackgroundWorker
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.clickup.client import ClickUpClient, ClickUpTask
from xw_office.services.mailing.service import MailDeliveryService
from xw_office.services.secrets.service import SecretService

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_OK_STYLE = "color: #4caf50; font-weight: bold;"
_WARN_STYLE = "color: #ffa726; font-weight: bold;"
_ERR_STYLE = "color: #ef5350; font-weight: bold;"
_INV_STOCK_KEY = "inventory.stock_levels"
_PENDING_REQ_KEY = "daily_business.pending_requirements"
_PENDING_COUNTS_KEY = "daily_business.pending_counts"
_QUEUE_MOLLIE_KEY = "daily_business.queue.mollie"
_QUEUE_GUTSCHEINE_KEY = "daily_business.queue.gutscheine"
_QUEUE_DOWNLOADS_KEY = "daily_business.queue.downloads"
_QUEUE_REFUNDS_KEY = "daily_business.queue.refunds"
_SENSITIVE_COUNTRIES_KEY = "rechnungen.sensitive_country_codes"
_ALLOWED_COUNTRIES_KEY = "rechnungen.allowed_country_codes"
_SKU_FLAGS_KEY = "rechnungen.sku_flags"
_URGENCY_RULES_KEY = "daily_business.urgency_rules"
_FULFILLMENT_MAIL_TEMPLATE_KEY = "rechnungen.fulfillment_mail_template_html"
_FULFILLMENT_MAIL_SUBJECT_KEY = "rechnungen.fulfillment_mail_subject"
_CLICKUP_LIST_ID_KEY = "clickup.default_list_id"
_TRANSFER_REQUIRED_SCOPES: tuple[str, ...] = (
    "Mail.ReadWrite",
    "Mail.ReadWrite.Shared",
)
_PLC_SECRET_KEYS: tuple[str, ...] = (
    "PLC_CLIENT_ID",
    "PLC_ORG_UNIT_ID",
    "PLC_ORG_UNIT_GUID",
    "PLC_LABEL_PRINTER",
    "PLC_LABEL_FORMAT_ID",
    "PLC_PAPER_LAYOUT_ID",
    "PLC_LABEL_LANGUAGE",
    "PLC_TIMEOUT_SECONDS",
    "PLC_SHIPPER_NAME1",
    "PLC_SHIPPER_NAME2",
    "PLC_SHIPPER_STREET",
    "PLC_SHIPPER_HOUSE_NUMBER",
    "PLC_SHIPPER_ADDRESS_LINE2",
    "PLC_SHIPPER_POSTAL_CODE",
    "PLC_SHIPPER_CITY",
    "PLC_SHIPPER_COUNTRY",
    "PLC_SHIPPER_PHONE",
    "PLC_SHIPPER_EMAIL",
    "PLC_SHIPPER_EORI",
)
_EXTRA_SECRET_KEYS: tuple[str, ...] = (
    "MOLLIE_ACCESS_TOKEN",
    "STRIPE_SECRET_KEY",
    "OPENAI_API_KEY",
    "CLICKUP_API_TOKEN",
    "GOOGLE_MAPS_API_KEY",
    "MS_GRAPH_CLIENT_ID",
    "MS_GRAPH_TENANT_ID",
    "MS_GRAPH_MAILBOX",
    "MS_GRAPH_TRANSFER_MAILBOX",
    "FON_TEILNEHMER_ID",
    "FON_BENUTZER_ID",
    "FON_PIN",
    "XW_SPECIAL_ORDER_ENDPOINT",
    "XW_SPECIAL_ORDER_SECRET",
)

_DEFAULT_FULFILLMENT_SUBJECT = "Ihre Rechnung {{invoice_number}}"
_DEFAULT_TEST_MAIL_RECIPIENT = "bernhard.holl@gmx.at"
_DEFAULT_FULFILLMENT_TEMPLATE = (
    "Guten Tag,\n\n"
    "wir freuen uns, Ihnen mitteilen zu können, dass Ihre Bestellung soeben versendet wurde.\n\n"
    "Die bestellten Produkte befinden sich nun auf dem Weg zu Ihnen. Je nach Versandart und Zielort kann die Zustellung einige Werktage in Anspruch nehmen.\n\n"
    "Die zugehörige Rechnung finden Sie im Anhang dieser E-Mail.\n\n"
    "Sollten Sie in der Zwischenzeit Fragen zu Ihrer Bestellung oder zum Lieferstatus haben, stehen wir Ihnen selbstverständlich gerne zur Verfügung.\n\n"
    "Vielen Dank für Ihr Vertrauen und Ihre Bestellung.\n\n"
    "Mit freundlichen Grüßen\n"
    "XeisWorks\n"
    "Mag. Bernhard Holl\n"
    "Johnsbach 92\n"
    "8912 Admont\n"
    "office@xeisworks.at\n"
    "www.xeisworks.at\n"
)
_DEFAULT_ALLOWED_COUNTRIES = json.dumps(
    [
        "Austria",
        "Germany",
        "Belgium",
        "Estonia",
        "Finland",
        "Denmark",
        "Slovenia",
        "Czech Republic",
        "Netherlands",
        "Sweden",
        "Lithuania",
        "Luxembourg",
        "France",
        "Italy",
        "Switzerland",
        "Norway",
        "Oesterreich",
        "Deutschland",
        "Schweiz",
        "Norwegen",
        "AT",
        "BE",
        "EE",
        "FI",
        "DK",
        "SI",
        "CZ",
        "NL",
        "SE",
        "LT",
        "LU",
        "FR",
        "DE",
        "IT",
        "CH",
        "NO",
    ],
    ensure_ascii=False,
)


def _pill(text: str, ok: bool) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_OK_STYLE if ok else _WARN_STYLE)
    return lbl


class SettingsView(QWidget):
    """Infrastructure status and configuration overview."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._db_worker: BackgroundWorker | None = None
        self._clickup_worker: BackgroundWorker | None = None
        self._mail_test_worker: BackgroundWorker | None = None
        self._queue_worker: BackgroundWorker | None = None
        self._template_worker: BackgroundWorker | None = None
        self._secret_worker: BackgroundWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_system_tab(), "System")
        tabs.addTab(self._build_preflight_tab(), "START-Daten")
        tabs.addTab(self._build_mail_templates_tab(), "Mail-Templates")
        outer.addWidget(tabs)

        self._load_queue_settings()
        self._load_fulfillment_mail_template()

    def _build_system_tab(self) -> QWidget:
        cfg = self._container.config
        secret_service: SecretService = self._container.resolve(SecretService)

        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        gb_db = QGroupBox("Datenbank (PostgreSQL / Railway)")
        form_db = QFormLayout(gb_db)
        db_url = (cfg.database_url or "").strip()
        form_db.addRow("DATABASE_URL:", _pill("gesetzt ✓", bool(db_url)) if db_url else _pill("fehlt ✗", False))
        self._db_status_lbl = QLabel("—")
        self._db_status_lbl.setStyleSheet("color: #9e9e9e;")
        form_db.addRow("Verbindung:", self._db_status_lbl)
        btn_test = QPushButton("Verbindung testen")
        btn_test.setFixedWidth(160)
        btn_test.clicked.connect(self._test_db)
        btn_test.setEnabled(bool(db_url))
        row_btn = QHBoxLayout()
        row_btn.addWidget(btn_test)
        row_btn.addStretch()
        form_db.addRow("", row_btn)
        grid.addWidget(gb_db, 0, 0)

        gb_secrets = QGroupBox("API-Zugangsdaten")
        form_sec = QFormLayout(gb_secrets)
        sevdesk_ok = bool(secret_service.get_secret("SEVDESK_API_TOKEN"))
        wix_ok = bool(secret_service.get_secret("WIX_API_KEY"))
        clickup_ok = bool(secret_service.get_secret("CLICKUP_API_TOKEN"))
        plc_ok = all(
            secret_service.get_secret(key)
            for key in ("PLC_CLIENT_ID", "PLC_ORG_UNIT_ID", "PLC_ORG_UNIT_GUID")
        )
        fernet_ok = bool((cfg.fernet_master_key or "").strip())
        form_sec.addRow("SEVDESK_API_TOKEN:", _pill("gesetzt ✓", sevdesk_ok) if sevdesk_ok else _pill("fehlt ✗", False))
        form_sec.addRow("WIX_API_KEY:", _pill("gesetzt ✓", wix_ok) if wix_ok else _pill("fehlt ✗", False))
        form_sec.addRow("CLICKUP_API_TOKEN:", _pill("gesetzt ✓", clickup_ok) if clickup_ok else _pill("fehlt ✗", False))
        form_sec.addRow("FERNET_MASTER_KEY:", _pill("gesetzt ✓", fernet_ok) if fernet_ok else _pill("fehlt ✗", False))
        form_sec.addRow("PLC-Webservice:", _pill("gesetzt", plc_ok) if plc_ok else _pill("fehlt", False))
        grid.addWidget(gb_secrets, 0, 1)

        gb_printer = QGroupBox("Drucker (konfiguriert)")
        form_pr = QFormLayout(gb_printer)
        printer_names = cfg.printing.configured_printer_names or []
        form_pr.addRow("Musik-DPI:", QLabel(str(cfg.printing.music_dpi)))
        form_pr.addRow("Rechnungs-DPI:", QLabel(str(cfg.printing.invoice_dpi)))
        form_pr.addRow("Puffer-Menge:", QLabel(str(cfg.printing.buffer_quantity)))
        if printer_names:
            for i, name in enumerate(printer_names, 1):
                form_pr.addRow(f"Drucker {i}:", QLabel(name))
        else:
            form_pr.addRow("Drucker:", _pill("keine konfiguriert", False))
        grid.addWidget(gb_printer, 1, 0)

        gb_clickup = QGroupBox("ClickUp Schnellanlage")
        clickup_form = QFormLayout(gb_clickup)
        self._clickup_list_id = QLineEdit(self._get_setting_value(_CLICKUP_LIST_ID_KEY))
        self._clickup_list_id.setPlaceholderText("ClickUp Listen-ID")
        self._clickup_title = QLineEdit()
        self._clickup_title.setPlaceholderText("Kurzbeschreibung der Aufgabe")
        self._clickup_description = QPlainTextEdit()
        self._clickup_description.setPlaceholderText("Details, Kontext, naechste Schritte")
        self._clickup_description.setMinimumHeight(90)
        clickup_form.addRow("Listen-ID:", self._clickup_list_id)
        clickup_form.addRow("Titel:", self._clickup_title)
        clickup_form.addRow("Beschreibung:", self._clickup_description)
        self._clickup_status = QLabel("—")
        self._clickup_status.setStyleSheet("color: #9e9e9e;")
        clickup_form.addRow("Status:", self._clickup_status)
        self._clickup_create_btn = QPushButton("Task in ClickUp erstellen")
        self._clickup_create_btn.clicked.connect(self._create_clickup_task)
        clickup_form.addRow("", self._clickup_create_btn)
        grid.addWidget(gb_clickup, 1, 1)

        gb_transfer_graph = QGroupBox("Transfer Graph Check (OFFENE UEBERWEISUNGEN)")
        transfer_form = QFormLayout(gb_transfer_graph)
        self._transfer_graph_mailbox = QLabel("—")
        self._transfer_graph_scopes = QLabel("—")
        self._transfer_graph_status = QLabel("—")
        self._transfer_graph_status.setStyleSheet("color: #9e9e9e;")
        btn_transfer_check = QPushButton("Check aktualisieren")
        btn_transfer_check.clicked.connect(self._refresh_transfer_graph_check)
        transfer_form.addRow("Mailbox:", self._transfer_graph_mailbox)
        transfer_form.addRow("Mindest-Scopes:", self._transfer_graph_scopes)
        transfer_form.addRow("Ampel:", self._transfer_graph_status)
        transfer_form.addRow("", btn_transfer_check)
        grid.addWidget(gb_transfer_graph, 2, 0)

        gb_secret_edit = QGroupBox("Token-Verwaltung (DB verschluesselt)")
        sec_edit = QFormLayout(gb_secret_edit)
        self._inp_sevdesk = QLineEdit(secret_service.get_secret("SEVDESK_API_TOKEN"))
        self._inp_sevdesk.setEchoMode(QLineEdit.EchoMode.Password)
        self._inp_wix = QLineEdit(secret_service.get_secret("WIX_API_KEY"))
        self._inp_wix.setEchoMode(QLineEdit.EchoMode.Password)
        self._inp_wix_site = QLineEdit(secret_service.get_secret("WIX_SITE_ID"))
        self._inp_wix_account = QLineEdit(secret_service.get_secret("WIX_ACCOUNT_ID"))
        sec_edit.addRow("sevDesk Token:", self._inp_sevdesk)
        sec_edit.addRow("Wix API Key:", self._inp_wix)
        sec_edit.addRow("Wix Site ID:", self._inp_wix_site)
        sec_edit.addRow("Wix Account ID:", self._inp_wix_account)
        self._extra_tokens_json = QPlainTextEdit()
        extra_tokens_obj = {
            key: secret_service.get_secret(key)
            for key in _EXTRA_SECRET_KEYS
            if secret_service.get_secret(key)
        }
        self._extra_tokens_json.setPlaceholderText('{"MOLLIE_ACCESS_TOKEN": "...", "STRIPE_SECRET_KEY": "..."}')
        self._extra_tokens_json.setPlainText(json.dumps(extra_tokens_obj, ensure_ascii=False, indent=2))
        self._extra_tokens_json.setMinimumHeight(100)
        sec_edit.addRow("Weitere Tokens (JSON):", self._extra_tokens_json)
        self._secret_status = QLabel("—")
        self._secret_status.setStyleSheet("color: #9e9e9e;")
        sec_edit.addRow("Status:", self._secret_status)
        btn_save_tokens = QPushButton("Tokens sicher speichern")
        btn_save_tokens.clicked.connect(self._save_tokens)
        sec_edit.addRow("", btn_save_tokens)
        grid.addWidget(gb_secret_edit, 3, 0, 1, 2)

        gb_plc = QGroupBox("Post Label Center (Direkt-Webservice)")
        plc_form = QFormLayout(gb_plc)
        plc_form.addRow(
            "Betrieb:",
            QLabel("Direkter Webservice ist Standard. Der Dateiimport bleibt nur als Fallback im PLC-Dialog."),
        )
        self._plc_client_id = QLineEdit(secret_service.get_secret("PLC_CLIENT_ID"))
        self._plc_org_unit_id = QLineEdit(secret_service.get_secret("PLC_ORG_UNIT_ID"))
        self._plc_org_unit_guid = QLineEdit(secret_service.get_secret("PLC_ORG_UNIT_GUID"))
        self._plc_org_unit_guid.setEchoMode(QLineEdit.EchoMode.Password)
        self._plc_label_printer = QLineEdit(secret_service.get_secret("PLC_LABEL_PRINTER"))
        self._plc_label_format_id = QLineEdit(secret_service.get_secret("PLC_LABEL_FORMAT_ID") or "100x200")
        self._plc_paper_layout_id = QLineEdit(secret_service.get_secret("PLC_PAPER_LAYOUT_ID") or "A5")
        self._plc_label_language = QLineEdit(secret_service.get_secret("PLC_LABEL_LANGUAGE") or "PDF")
        self._plc_timeout_seconds = QLineEdit(secret_service.get_secret("PLC_TIMEOUT_SECONDS") or "45")
        self._plc_shipper_name1 = QLineEdit(secret_service.get_secret("PLC_SHIPPER_NAME1"))
        self._plc_shipper_name2 = QLineEdit(secret_service.get_secret("PLC_SHIPPER_NAME2"))
        self._plc_shipper_street = QLineEdit(secret_service.get_secret("PLC_SHIPPER_STREET"))
        self._plc_shipper_house_number = QLineEdit(secret_service.get_secret("PLC_SHIPPER_HOUSE_NUMBER"))
        self._plc_shipper_address_line2 = QLineEdit(secret_service.get_secret("PLC_SHIPPER_ADDRESS_LINE2"))
        self._plc_shipper_postal_code = QLineEdit(secret_service.get_secret("PLC_SHIPPER_POSTAL_CODE"))
        self._plc_shipper_city = QLineEdit(secret_service.get_secret("PLC_SHIPPER_CITY"))
        self._plc_shipper_country = QLineEdit(secret_service.get_secret("PLC_SHIPPER_COUNTRY") or "AT")
        self._plc_shipper_phone = QLineEdit(secret_service.get_secret("PLC_SHIPPER_PHONE"))
        self._plc_shipper_email = QLineEdit(secret_service.get_secret("PLC_SHIPPER_EMAIL"))
        self._plc_shipper_eori = QLineEdit(secret_service.get_secret("PLC_SHIPPER_EORI"))
        self._plc_client_id.setPlaceholderText("PLC: Gerätekonfiguration → Organisation → API")
        self._plc_org_unit_id.setPlaceholderText("PLC-Abteilungs-ID")
        self._plc_org_unit_guid.setPlaceholderText("PLC-Abteilungs-GUID")
        self._plc_label_printer.setPlaceholderText("leer = bestehender Label-Drucker")
        plc_form.addRow("Client ID:", self._plc_client_id)
        plc_form.addRow("Org Unit ID:", self._plc_org_unit_id)
        plc_form.addRow("Org Unit GUID:", self._plc_org_unit_guid)
        plc_form.addRow("PLC-Labeldrucker:", self._plc_label_printer)
        plc_form.addRow("PLC Label-Format:", self._plc_label_format_id)
        plc_form.addRow("PLC Papierlayout:", self._plc_paper_layout_id)
        plc_form.addRow("PLC Drucksprache:", self._plc_label_language)
        plc_form.addRow("PLC Timeout (Sek.):", self._plc_timeout_seconds)
        plc_form.addRow("Absender Name 1:", self._plc_shipper_name1)
        plc_form.addRow("Absender Name 2:", self._plc_shipper_name2)
        plc_form.addRow("Absender Straße:", self._plc_shipper_street)
        plc_form.addRow("Absender Hausnummer:", self._plc_shipper_house_number)
        plc_form.addRow("Absender Zusatz:", self._plc_shipper_address_line2)
        plc_form.addRow("Absender PLZ:", self._plc_shipper_postal_code)
        plc_form.addRow("Absender Ort:", self._plc_shipper_city)
        plc_form.addRow("Absender Land (ISO-2):", self._plc_shipper_country)
        plc_form.addRow("Absender Telefon:", self._plc_shipper_phone)
        plc_form.addRow("Absender E-Mail:", self._plc_shipper_email)
        plc_form.addRow("Absender EORI:", self._plc_shipper_eori)
        plc_form.addRow("Vorgabe:", QLabel("PDF · 100x200 · A5 (für Paketmarke A5)"))
        self._plc_status = QLabel("—")
        self._plc_status.setStyleSheet("color: #9e9e9e;")
        plc_form.addRow("Status:", self._plc_status)
        plc_save = QPushButton("PLC-Konfiguration sicher speichern")
        plc_save.clicked.connect(self._save_plc_settings)
        plc_form.addRow("", plc_save)
        grid.addWidget(gb_plc, 4, 0, 1, 2)

        self._refresh_transfer_graph_check()

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(5, 1)
        return panel

    def _refresh_transfer_graph_check(self) -> None:
        secret_service: SecretService = self._container.resolve(SecretService)
        tenant_id = secret_service.get_secret("MS_GRAPH_TENANT_ID")
        client_id = secret_service.get_secret("MS_GRAPH_CLIENT_ID")
        transfer_mailbox = secret_service.get_secret("MS_GRAPH_TRANSFER_MAILBOX")
        default_mailbox = secret_service.get_secret("MS_GRAPH_MAILBOX")

        mailbox = str(transfer_mailbox or "").strip() or "transfer@xeisworks.at"
        self._transfer_graph_mailbox.setText(mailbox)

        configured_scopes = {
            "Mail.Read",
            "Mail.Read.Shared",
            "Mail.ReadWrite",
            "Mail.ReadWrite.Shared",
            "Mail.Send",
            "Mail.Send.Shared",
        }
        missing_scopes = [scope for scope in _TRANSFER_REQUIRED_SCOPES if scope not in configured_scopes]
        if missing_scopes:
            self._transfer_graph_scopes.setText(f"fehlt: {', '.join(missing_scopes)}")
            self._transfer_graph_scopes.setStyleSheet(_ERR_STYLE)
        else:
            self._transfer_graph_scopes.setText("ok: Mail.ReadWrite, Mail.ReadWrite.Shared")
            self._transfer_graph_scopes.setStyleSheet(_OK_STYLE)

        missing_config = [
            key
            for key, value in (
                ("MS_GRAPH_TENANT_ID", tenant_id),
                ("MS_GRAPH_CLIENT_ID", client_id),
            )
            if not str(value or "").strip()
        ]

        if missing_config:
            self._transfer_graph_status.setText(f"ROT - fehlend: {', '.join(missing_config)}")
            self._transfer_graph_status.setStyleSheet(_ERR_STYLE)
            return
        if not transfer_mailbox and default_mailbox:
            self._transfer_graph_status.setText(
                "GELB - MS_GRAPH_TRANSFER_MAILBOX fehlt, Fallback auf Default-Mailbox aktiv"
            )
            self._transfer_graph_status.setStyleSheet(_WARN_STYLE)
            return
        if missing_scopes:
            self._transfer_graph_status.setText("GELB - Scope-Konfiguration unvollstaendig")
            self._transfer_graph_status.setStyleSheet(_WARN_STYLE)
            return

        self._transfer_graph_status.setText("GRUEN - Transfer Graph Startcheck ok")
        self._transfer_graph_status.setStyleSheet(_OK_STYLE)

    def _json_box(self, key: str, placeholder: str, min_height: int) -> tuple[QGroupBox, QPlainTextEdit]:
        box = QGroupBox(key)
        layout = QVBoxLayout(box)
        editor = QPlainTextEdit()
        editor.setPlaceholderText(placeholder)
        editor.setMinimumHeight(min_height)
        layout.addWidget(editor)
        return box, editor

    def _build_preflight_tab(self) -> QWidget:
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        intro = QLabel(
            "Definiert die Druckentscheidung im START-Dialog. "
            "JSON-Felder sind in Spalten organisiert, um schneller zu arbeiten."
        )
        intro.setWordWrap(True)
        grid.addWidget(intro, 0, 0, 1, 2)

        stock_box, self._stock_json = self._json_box(_INV_STOCK_KEY, '{"XW-4-001": 5, "XW-6-003": 1}', 90)
        pending_box, self._pending_json = self._json_box(_PENDING_REQ_KEY, '{"XW-4-001": 7, "XW-6-003": 2}', 90)
        pending_counts_box, self._pending_counts_json = self._json_box(
            _PENDING_COUNTS_KEY,
            '{"mollie": 3, "gutscheine": 1, "downloads": 2, "refunds": 0}',
            80,
        )
        mollie_box, self._queue_mollie_json = self._json_box(
            _QUEUE_MOLLIE_KEY,
            '[{"ref": "MOL-1001", "customer": "Max Mustermann", "amount": "19.90", "status": "Authorized", "note": "wartet auf Rechnung"}]',
            90,
        )
        gutscheine_box, self._queue_gutscheine_json = self._json_box(
            _QUEUE_GUTSCHEINE_KEY,
            '[{"ref": "GUT-23", "customer": "Erika Muster", "status": "Offen"}]',
            80,
        )
        downloads_box, self._queue_downloads_json = self._json_box(
            _QUEUE_DOWNLOADS_KEY,
            '[{"ref": "DL-1", "customer": "Demo", "status": "Bereit"}]',
            80,
        )
        refunds_box, self._queue_refunds_json = self._json_box(
            _QUEUE_REFUNDS_KEY,
            '[{"ref": "RF-77", "customer": "Demo", "amount": "-9.90", "status": "Offen"}]',
            80,
        )
        countries_box, self._sensitive_countries_json = self._json_box(
            _SENSITIVE_COUNTRIES_KEY,
            '["RU", "IR", "SY"]',
            70,
        )
        allowed_countries_box, self._allowed_countries_json = self._json_box(
            _ALLOWED_COUNTRIES_KEY,
            _DEFAULT_ALLOWED_COUNTRIES,
            110,
        )
        sku_flags_box, self._sku_flags_json = self._json_box(
            _SKU_FLAGS_KEY,
            '{"exact": ["XW-010", "XW-011"], "prefixes": ["XW-4", "XW-6", "XW-7"]}',
            90,
        )
        urgency_box, self._urgency_rules_json = self._json_box(
            _URGENCY_RULES_KEY,
            '{"generic": ["offen", "pending"], "mollie": ["authorized", "chargeback"], "gutscheine": ["ungueltig"], "downloads": ["link fehlt"], "refunds": ["refund"]}',
            100,
        )

        grid.addWidget(stock_box, 1, 0)
        grid.addWidget(pending_box, 1, 1)
        grid.addWidget(pending_counts_box, 2, 0)
        grid.addWidget(mollie_box, 2, 1)
        grid.addWidget(gutscheine_box, 3, 0)
        grid.addWidget(downloads_box, 3, 1)
        grid.addWidget(refunds_box, 4, 0)
        grid.addWidget(countries_box, 4, 1)
        grid.addWidget(sku_flags_box, 5, 0)
        grid.addWidget(allowed_countries_box, 5, 1)
        grid.addWidget(urgency_box, 6, 0, 1, 2)

        footer = QHBoxLayout()
        self._queue_status = QLabel("—")
        self._queue_status.setStyleSheet("color: #9e9e9e;")
        footer.addWidget(self._queue_status)
        footer.addStretch()
        save_queue = QPushButton("Queue speichern")
        save_queue.clicked.connect(self._save_queue_settings)
        save_queue.setEnabled(self._has_settings_repo())
        footer.addWidget(save_queue)
        grid.addLayout(footer, 7, 0, 1, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(8, 1)
        return panel

    def _build_mail_templates_tab(self) -> QWidget:
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        gb_template = QGroupBox("Rechnungsmail-Vorlage")
        template_layout = QVBoxLayout(gb_template)
        info = QLabel(
            "Variablen: {{customer_name}}, {{invoice_number}}, {{download_link}}, {{items_html}}"
        )
        info.setWordWrap(True)
        template_layout.addWidget(info)

        subject_row = QFormLayout()
        self._mail_subject_editor = QLineEdit()
        self._mail_subject_editor.setPlaceholderText(_DEFAULT_FULFILLMENT_SUBJECT)
        subject_row.addRow("Betreff-Vorlage:", self._mail_subject_editor)
        template_layout.addLayout(subject_row)

        body_lbl = QLabel("Nachrichtentext:")
        template_layout.addWidget(body_lbl)

        self._mail_template_editor = QPlainTextEdit()
        self._mail_template_editor.setMinimumHeight(320)
        self._mail_template_editor.setPlaceholderText(_DEFAULT_FULFILLMENT_TEMPLATE)
        template_layout.addWidget(self._mail_template_editor)

        mail_btn_row = QHBoxLayout()
        btn_preview = QPushButton("Vorschau aktualisieren")
        btn_preview.clicked.connect(self._render_fulfillment_preview)
        mail_btn_row.addWidget(btn_preview)
        btn_save_template = QPushButton("Vorlage speichern")
        btn_save_template.clicked.connect(self._save_fulfillment_mail_template)
        btn_save_template.setEnabled(self._has_settings_repo())
        mail_btn_row.addWidget(btn_save_template)
        self._mail_test_recipient = QLineEdit(_DEFAULT_TEST_MAIL_RECIPIENT)
        self._mail_test_recipient.setPlaceholderText("Empfänger Test-Mail")
        self._mail_test_recipient.setMinimumWidth(240)
        mail_btn_row.addWidget(self._mail_test_recipient)
        btn_send_test = QPushButton("Rechnungsmail testen")
        btn_send_test.clicked.connect(self._send_template_test_mail)
        mail_btn_row.addWidget(btn_send_test)
        mail_btn_row.addStretch()
        template_layout.addLayout(mail_btn_row)

        self._mail_template_status = QLabel("—")
        self._mail_template_status.setStyleSheet("color: #9e9e9e;")
        template_layout.addWidget(self._mail_template_status)

        gb_html = QGroupBox("HTML-Ansicht Rechnungsmail")
        html_layout = QVBoxLayout(gb_html)
        self._mail_subject_preview = QLabel("Betreff: —")
        self._mail_subject_preview.setTextInteractionFlags(self._mail_subject_preview.textInteractionFlags())
        html_layout.addWidget(self._mail_subject_preview)
        self._mail_template_preview = QTextBrowser()
        self._mail_template_preview.setOpenExternalLinks(True)
        self._mail_template_preview.setMinimumHeight(420)
        html_layout.addWidget(self._mail_template_preview)

        gb_plain = QGroupBox("Nur-Text-Ansicht Rechnungsmail")
        plain_layout = QVBoxLayout(gb_plain)
        self._mail_template_plain_preview = QPlainTextEdit()
        self._mail_template_plain_preview.setReadOnly(True)
        self._mail_template_plain_preview.setMinimumHeight(420)
        plain_layout.addWidget(self._mail_template_plain_preview)

        grid.addWidget(gb_template, 0, 0)
        grid.addWidget(gb_html, 0, 1)
        grid.addWidget(gb_plain, 0, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        return panel

    def _test_db(self) -> None:
        if self._db_worker is not None and self._db_worker.isRunning():
            return
        self._db_status_lbl.setText("Prüfe…")
        self._db_status_lbl.setStyleSheet("color: #9e9e9e;")
        cfg = self._container.config

        def ping() -> str:
            try:
                from sqlalchemy import text  # local import keeps startup lean
                from xw_office.core.database import create_engine_from_config
                engine = create_engine_from_config(cfg)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return "ok"
            except Exception as exc:
                return str(exc)

        self._db_worker = BackgroundWorker(ping)
        self._db_worker.signals.result.connect(self._on_db_result)
        self._db_worker.signals.error.connect(self._on_db_error)
        self._db_worker.start()

    def _on_db_result(self, result: object) -> None:
        msg = str(result)
        if msg == "ok":
            self._db_status_lbl.setText("Verbunden ✓")
            self._db_status_lbl.setStyleSheet(_OK_STYLE)
        else:
            short = msg[:120] + ("…" if len(msg) > 120 else "")
            self._db_status_lbl.setText(f"Fehler: {short}")
            self._db_status_lbl.setStyleSheet(_ERR_STYLE)

    def _on_db_error(self, exc: Exception) -> None:
        logger.error("DB ping failed: %s", exc)
        self._db_status_lbl.setText(f"Fehler: {exc}")
        self._db_status_lbl.setStyleSheet(_ERR_STYLE)

    def _has_settings_repo(self) -> bool:
        try:
            self._container.resolve(SettingKvRepository)
            return True
        except KeyError:
            return False

    def _get_setting_value(self, key: str) -> str:
        if not self._has_settings_repo():
            return ""
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        return repo.get_value_json(key) or ""

    def _set_setting_value(self, key: str, value: str) -> None:
        if not self._has_settings_repo():
            return
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        repo.set_value_json(key, value)

    def _load_queue_settings(self) -> None:
        if not self._has_settings_repo():
            self._queue_status.setText("DB-Repository nicht aktiv (DATABASE_URL fehlt oder Migration fehlt).")
            self._queue_status.setStyleSheet(_WARN_STYLE)
            return
        if self._queue_worker is not None and self._queue_worker.isRunning():
            return
        self._queue_status.setText("START-Daten werden aus der DB geladen...")
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)

        def job() -> dict[str, str]:
            return {
                "stock": repo.get_value_json(_INV_STOCK_KEY) or "{}",
                "pending": repo.get_value_json(_PENDING_REQ_KEY) or "{}",
                "pending_counts": repo.get_value_json(_PENDING_COUNTS_KEY) or "{}",
                "mollie": repo.get_value_json(_QUEUE_MOLLIE_KEY) or "[]",
                "gutscheine": repo.get_value_json(_QUEUE_GUTSCHEINE_KEY) or "[]",
                "downloads": repo.get_value_json(_QUEUE_DOWNLOADS_KEY) or "[]",
                "refunds": repo.get_value_json(_QUEUE_REFUNDS_KEY) or "[]",
                "sensitive": repo.get_value_json(_SENSITIVE_COUNTRIES_KEY) or '["AF", "BY", "IQ", "IR", "KP", "RU", "SY"]',
                "allowed": repo.get_value_json(_ALLOWED_COUNTRIES_KEY) or _DEFAULT_ALLOWED_COUNTRIES,
                "sku_flags": repo.get_value_json(_SKU_FLAGS_KEY) or '{"exact": ["XW-010", "XW-011", "XW-600.0"], "prefixes": ["XW-4", "XW-6", "XW-7", "XW-12"], "suffixes": ["-P"]}',
                "urgency": repo.get_value_json(_URGENCY_RULES_KEY) or '{"generic": ["offen", "fehl", "pending", "ueberweis"]}',
            }

        self._queue_worker = BackgroundWorker(job)
        self._queue_worker.signals.result.connect(self._on_queue_settings_loaded)
        self._queue_worker.signals.error.connect(
            lambda exc: self._queue_status.setText(f"Laden fehlgeschlagen: {exc}")
        )
        self._queue_worker.signals.finished.connect(lambda: setattr(self, "_queue_worker", None))
        self._queue_worker.start()

    def _on_queue_settings_loaded(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._stock_json.setPlainText(str(payload.get("stock") or "{}"))
        self._pending_json.setPlainText(str(payload.get("pending") or "{}"))
        self._pending_counts_json.setPlainText(str(payload.get("pending_counts") or "{}"))
        self._queue_mollie_json.setPlainText(str(payload.get("mollie") or "[]"))
        self._queue_gutscheine_json.setPlainText(str(payload.get("gutscheine") or "[]"))
        self._queue_downloads_json.setPlainText(str(payload.get("downloads") or "[]"))
        self._queue_refunds_json.setPlainText(str(payload.get("refunds") or "[]"))
        self._sensitive_countries_json.setPlainText(str(payload.get("sensitive") or "[]"))
        self._allowed_countries_json.setPlainText(str(payload.get("allowed") or "[]"))
        self._sku_flags_json.setPlainText(str(payload.get("sku_flags") or "{}"))
        self._urgency_rules_json.setPlainText(str(payload.get("urgency") or "{}"))
        self._queue_status.setText("Aktueller Stand aus DB geladen.")
        self._queue_status.setStyleSheet(_OK_STYLE)

    def _save_queue_settings(self) -> None:
        if self._queue_worker is not None and self._queue_worker.isRunning():
            return
        if not self._has_settings_repo():
            QMessageBox.warning(self, "Fehler", "DB-Repository nicht verfuegbar.")
            return
        stock_raw = self._stock_json.toPlainText().strip() or "{}"
        pending_raw = self._pending_json.toPlainText().strip() or "{}"
        pending_counts_raw = self._pending_counts_json.toPlainText().strip() or "{}"
        queue_mollie_raw = self._queue_mollie_json.toPlainText().strip() or "[]"
        queue_gutscheine_raw = self._queue_gutscheine_json.toPlainText().strip() or "[]"
        queue_downloads_raw = self._queue_downloads_json.toPlainText().strip() or "[]"
        queue_refunds_raw = self._queue_refunds_json.toPlainText().strip() or "[]"
        sensitive_countries_raw = self._sensitive_countries_json.toPlainText().strip() or "[]"
        allowed_countries_raw = self._allowed_countries_json.toPlainText().strip() or "[]"
        sku_flags_raw = self._sku_flags_json.toPlainText().strip() or "{}"
        urgency_rules_raw = self._urgency_rules_json.toPlainText().strip() or "{}"
        try:
            stock_obj = json.loads(stock_raw)
            pending_obj = json.loads(pending_raw)
            pending_counts_obj = json.loads(pending_counts_raw)
            queue_mollie_obj = json.loads(queue_mollie_raw)
            queue_gutscheine_obj = json.loads(queue_gutscheine_raw)
            queue_downloads_obj = json.loads(queue_downloads_raw)
            queue_refunds_obj = json.loads(queue_refunds_raw)
            sensitive_countries_obj = json.loads(sensitive_countries_raw)
            allowed_countries_obj = json.loads(allowed_countries_raw)
            sku_flags_obj = json.loads(sku_flags_raw)
            urgency_rules_obj = json.loads(urgency_rules_raw)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "JSON-Fehler", f"Ungueltiges JSON:\n\n{exc}")
            return
        if (
            not isinstance(stock_obj, dict)
            or not isinstance(pending_obj, dict)
            or not isinstance(pending_counts_obj, dict)
            or not isinstance(queue_mollie_obj, list)
            or not isinstance(queue_gutscheine_obj, list)
            or not isinstance(queue_downloads_obj, list)
            or not isinstance(queue_refunds_obj, list)
            or not isinstance(sensitive_countries_obj, list)
            or not isinstance(allowed_countries_obj, list)
            or not isinstance(sku_flags_obj, dict)
            or not isinstance(urgency_rules_obj, dict)
        ):
            QMessageBox.warning(
                self,
                "Formatfehler",
                "Stock/Pending/Counts muessen Objekte sein; Queue/Country-Listen muessen Listen sein; SKU-Flags/Urgency-Rules muessen Objekte sein.",
            )
            return

        exact_raw = sku_flags_obj.get("exact") if isinstance(sku_flags_obj, dict) else None
        prefixes_raw = sku_flags_obj.get("prefixes") if isinstance(sku_flags_obj, dict) else None
        suffixes_raw = sku_flags_obj.get("suffixes", ["-P"]) if isinstance(sku_flags_obj, dict) else None
        if not isinstance(exact_raw, list) or not isinstance(prefixes_raw, list):
            QMessageBox.warning(
                self,
                "Formatfehler",
                "SKU-Flags braucht das Format: {\"exact\": [...], \"prefixes\": [...], \"suffixes\": [...]}.",
            )
            return
        if not isinstance(suffixes_raw, list):
            suffixes_raw = ["-P"]

        normalized_sensitive = [
            str(code).strip().upper()
            for code in sensitive_countries_obj
            if str(code).strip()
        ]
        normalized_allowed_countries = [
            str(code).strip()
            for code in allowed_countries_obj
            if str(code).strip()
        ]
        normalized_sku_flags = {
            "exact": [
                str(code).strip().upper()
                for code in exact_raw
                if str(code).strip()
            ],
            "prefixes": [
                str(code).strip().upper()
                for code in prefixes_raw
                if str(code).strip()
            ],
            "suffixes": [
                str(code).strip().upper()
                for code in suffixes_raw
                if str(code).strip()
            ],
        }
        normalized_rules = {
            key: [
                str(token).strip().lower()
                for token in value
                if str(token).strip()
            ]
            for key, value in urgency_rules_obj.items()
            if isinstance(key, str) and isinstance(value, list)
        }

        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        values = {
            _INV_STOCK_KEY: json.dumps(stock_obj),
            _PENDING_REQ_KEY: json.dumps(pending_obj),
            _PENDING_COUNTS_KEY: json.dumps(pending_counts_obj),
            _QUEUE_MOLLIE_KEY: json.dumps(queue_mollie_obj),
            _QUEUE_GUTSCHEINE_KEY: json.dumps(queue_gutscheine_obj),
            _QUEUE_DOWNLOADS_KEY: json.dumps(queue_downloads_obj),
            _QUEUE_REFUNDS_KEY: json.dumps(queue_refunds_obj),
            _SENSITIVE_COUNTRIES_KEY: json.dumps(normalized_sensitive),
            _ALLOWED_COUNTRIES_KEY: json.dumps(normalized_allowed_countries, ensure_ascii=False),
            _SKU_FLAGS_KEY: json.dumps(normalized_sku_flags),
            _URGENCY_RULES_KEY: json.dumps(normalized_rules),
        }
        self._queue_status.setText("Queue-Daten werden gespeichert...")

        def job() -> bool:
            for key, value in values.items():
                repo.set_value_json(key, value)
            return True

        self._queue_worker = BackgroundWorker(job)
        self._queue_worker.signals.result.connect(self._on_queue_settings_saved)
        self._queue_worker.signals.error.connect(
            lambda exc: self._queue_status.setText(f"Speichern fehlgeschlagen: {exc}")
        )
        self._queue_worker.signals.finished.connect(lambda: setattr(self, "_queue_worker", None))
        self._queue_worker.start()

    def _on_queue_settings_saved(self, _payload: object) -> None:
        self._queue_status.setText("Queue-Daten gespeichert.")
        self._queue_status.setStyleSheet(_OK_STYLE)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("START-Preflight-Daten gespeichert", 4000)

    def _load_fulfillment_mail_template(self) -> None:
        if not self._has_settings_repo():
            self._mail_subject_editor.setText(_DEFAULT_FULFILLMENT_SUBJECT)
            self._mail_template_editor.setPlainText(_DEFAULT_FULFILLMENT_TEMPLATE)
            self._render_fulfillment_preview()
            return
        if self._template_worker is not None and self._template_worker.isRunning():
            return
        self._mail_template_status.setText("Vorlage wird geladen...")
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)

        def job() -> tuple[str, str]:
            subject = repo.get_value_json(_FULFILLMENT_MAIL_SUBJECT_KEY) or _DEFAULT_FULFILLMENT_SUBJECT
            raw = repo.get_value_json(_FULFILLMENT_MAIL_TEMPLATE_KEY) or _DEFAULT_FULFILLMENT_TEMPLATE
            return subject, raw

        self._template_worker = BackgroundWorker(job)
        self._template_worker.signals.result.connect(self._on_fulfillment_template_loaded)
        self._template_worker.signals.error.connect(
            lambda exc: self._mail_template_status.setText(f"Laden fehlgeschlagen: {exc}")
        )
        self._template_worker.signals.finished.connect(
            lambda: setattr(self, "_template_worker", None)
        )
        self._template_worker.start()

    def _on_fulfillment_template_loaded(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        subject, raw = payload
        self._mail_subject_editor.setText(str(subject))
        self._mail_template_editor.setPlainText(str(raw))
        self._render_fulfillment_preview()

    def _render_fulfillment_preview(self) -> None:
        subject_template = self._mail_subject_editor.text().strip() or _DEFAULT_FULFILLMENT_SUBJECT
        body_template = self._mail_template_editor.toPlainText().strip() or _DEFAULT_FULFILLMENT_TEMPLATE
        preview = body_template
        substitutions = {
            "{{customer_name}}": "Max Mustermann",
            "{{invoice_number}}": "RE-2026-0042",
            "{{download_link}}": "https://example.com/download/RE-2026-0042",
            "{{items_html}}": "XW-7001 - 1x Brandlalm Boarischer\nXW-600.0 - 2x Zusatzstimme",
        }
        subject_preview = subject_template
        for token, value in substitutions.items():
            preview = preview.replace(token, value)
            subject_preview = subject_preview.replace(token, value)
        self._mail_subject_preview.setText(f"Betreff: {subject_preview}")
        if "<" in preview and ">" in preview:
            self._mail_template_preview.setHtml(preview)
            doc = QTextDocument()
            doc.setHtml(preview)
            plain_preview = doc.toPlainText()
        else:
            html_preview = "<div style=\"white-space:pre-wrap;\">" + html.escape(preview) + "</div>"
            self._mail_template_preview.setHtml(html_preview)
            plain_preview = preview
        self._mail_template_plain_preview.setPlainText(plain_preview)
        self._mail_template_status.setText("Vorschau aktualisiert")
        self._mail_template_status.setStyleSheet(_OK_STYLE)

    def _save_fulfillment_mail_template(self) -> None:
        if self._template_worker is not None and self._template_worker.isRunning():
            return
        if not self._has_settings_repo():
            QMessageBox.warning(self, "Fehler", "DB-Repository nicht verfuegbar.")
            return
        subject = self._mail_subject_editor.text().strip() or _DEFAULT_FULFILLMENT_SUBJECT
        body = self._mail_template_editor.toPlainText().strip() or _DEFAULT_FULFILLMENT_TEMPLATE
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        self._mail_template_status.setText("Vorlage wird gespeichert...")

        def job() -> bool:
            repo.set_value_json(_FULFILLMENT_MAIL_SUBJECT_KEY, subject)
            repo.set_value_json(_FULFILLMENT_MAIL_TEMPLATE_KEY, body)
            return True

        self._template_worker = BackgroundWorker(job)
        self._template_worker.signals.result.connect(self._on_fulfillment_template_saved)
        self._template_worker.signals.error.connect(
            lambda exc: self._mail_template_status.setText(f"Speichern fehlgeschlagen: {exc}")
        )
        self._template_worker.signals.finished.connect(
            lambda: setattr(self, "_template_worker", None)
        )
        self._template_worker.start()

    def _on_fulfillment_template_saved(self, _payload: object) -> None:
        self._mail_template_status.setText("Vorlage gespeichert")
        self._mail_template_status.setStyleSheet(_OK_STYLE)
        self._render_fulfillment_preview()

    def _send_template_test_mail(self) -> None:
        if self._mail_test_worker is not None and self._mail_test_worker.isRunning():
            return
        recipient = self._mail_test_recipient.text().strip()
        if not recipient:
            QMessageBox.warning(self, "Test-Mail", "Bitte Empfängeradresse eingeben.")
            return

        subject_template = self._mail_subject_editor.text().strip() or _DEFAULT_FULFILLMENT_SUBJECT
        body_template = self._mail_template_editor.toPlainText().strip() or _DEFAULT_FULFILLMENT_TEMPLATE
        substitutions = {
            "{{customer_name}}": "Bernhard Holl",
            "{{invoice_number}}": "RE-TEST-0001",
            "{{download_link}}": "",
            "{{items_html}}": "XW-TEST - 1x Testartikel",
        }
        subject = subject_template
        body = body_template
        for token, value in substitutions.items():
            subject = subject.replace(token, value)
            body = body.replace(token, value)

        self._mail_template_status.setText("Sende Test-Mail...")
        self._mail_template_status.setStyleSheet(_WARN_STYLE)
        mailer: MailDeliveryService = self._container.resolve(MailDeliveryService)
        if not mailer.is_configured():
            QMessageBox.warning(
                self,
                "Test-Mail",
                "Bitte zuerst MS Graph konfigurieren (fehlend: MS_GRAPH_TENANT_ID, MS_GRAPH_CLIENT_ID oder MS_GRAPH_MAILBOX).",
            )
            self._mail_template_status.setText("MS-Graph-Konfiguration fehlt")
            self._mail_template_status.setStyleSheet(_ERR_STYLE)
            return

        def job() -> str:
            mailer.send_mail(
                to_email=recipient,
                subject=subject,
                text_body=body,
                html_body=(
                    "<html><body style=\"font-family:Segoe UI,Arial,sans-serif;color:#0f172a;line-height:1.5;\">"
                    f"{mailer.plain_text_to_html(body)}"
                    "</body></html>"
                ),
            )
            return recipient

        self._mail_test_worker = BackgroundWorker(job)
        self._mail_test_worker.signals.result.connect(self._on_test_mail_sent)
        self._mail_test_worker.signals.error.connect(self._on_test_mail_error)
        self._mail_test_worker.start()

    def _on_test_mail_sent(self, result: object) -> None:
        target = str(result or self._mail_test_recipient.text().strip() or "Empfänger")
        self._mail_template_status.setText(f"Test-Mail gesendet an {target}")
        self._mail_template_status.setStyleSheet(_OK_STYLE)
        QMessageBox.information(self, "Test-Mail", f"Test-Mail erfolgreich gesendet an {target}.")

    def _on_test_mail_error(self, exc: Exception) -> None:
        self._mail_template_status.setText(f"Test-Mail fehlgeschlagen: {exc}")
        self._mail_template_status.setStyleSheet(_ERR_STYLE)
        QMessageBox.warning(self, "Test-Mail", f"Senden fehlgeschlagen:\n\n{exc}")

    def _save_plc_settings(self) -> None:
        if self._secret_worker is not None and self._secret_worker.isRunning():
            return
        values = {
            "PLC_CLIENT_ID": self._plc_client_id.text().strip(),
            "PLC_ORG_UNIT_ID": self._plc_org_unit_id.text().strip(),
            "PLC_ORG_UNIT_GUID": self._plc_org_unit_guid.text().strip(),
            "PLC_LABEL_PRINTER": self._plc_label_printer.text().strip(),
            "PLC_LABEL_FORMAT_ID": self._plc_label_format_id.text().strip(),
            "PLC_PAPER_LAYOUT_ID": self._plc_paper_layout_id.text().strip(),
            "PLC_LABEL_LANGUAGE": self._plc_label_language.text().strip().upper(),
            "PLC_TIMEOUT_SECONDS": self._plc_timeout_seconds.text().strip(),
            "PLC_SHIPPER_NAME1": self._plc_shipper_name1.text().strip(),
            "PLC_SHIPPER_NAME2": self._plc_shipper_name2.text().strip(),
            "PLC_SHIPPER_STREET": self._plc_shipper_street.text().strip(),
            "PLC_SHIPPER_HOUSE_NUMBER": self._plc_shipper_house_number.text().strip(),
            "PLC_SHIPPER_ADDRESS_LINE2": self._plc_shipper_address_line2.text().strip(),
            "PLC_SHIPPER_POSTAL_CODE": self._plc_shipper_postal_code.text().strip(),
            "PLC_SHIPPER_CITY": self._plc_shipper_city.text().strip(),
            "PLC_SHIPPER_COUNTRY": self._plc_shipper_country.text().strip().upper(),
            "PLC_SHIPPER_PHONE": self._plc_shipper_phone.text().strip(),
            "PLC_SHIPPER_EMAIL": self._plc_shipper_email.text().strip(),
            "PLC_SHIPPER_EORI": self._plc_shipper_eori.text().strip(),
        }
        required = (
            "PLC_CLIENT_ID",
            "PLC_ORG_UNIT_ID",
            "PLC_ORG_UNIT_GUID",
            "PLC_SHIPPER_NAME1",
            "PLC_SHIPPER_STREET",
            "PLC_SHIPPER_HOUSE_NUMBER",
            "PLC_SHIPPER_POSTAL_CODE",
            "PLC_SHIPPER_CITY",
            "PLC_SHIPPER_COUNTRY",
        )
        missing = [key for key in required if not values[key]]
        if missing:
            message = "Fehlende PLC-Pflichtfelder: " + ", ".join(missing)
            self._plc_status.setText(message)
            self._plc_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "PLC-Konfiguration", message)
            return
        if not values["PLC_CLIENT_ID"].isdigit() or not values["PLC_ORG_UNIT_ID"].isdigit():
            message = "Client ID und Org Unit ID müssen Zahlen sein."
            self._plc_status.setText(message)
            self._plc_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "PLC-Konfiguration", message)
            return
        if not all(
            values[key]
            for key in ("PLC_LABEL_FORMAT_ID", "PLC_PAPER_LAYOUT_ID", "PLC_LABEL_LANGUAGE", "PLC_TIMEOUT_SECONDS")
        ):
            message = "PLC-Label-Format, Papierlayout, Drucksprache und Timeout müssen gesetzt sein."
            self._plc_status.setText(message)
            self._plc_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "PLC-Konfiguration", message)
            return
        try:
            if float(values["PLC_TIMEOUT_SECONDS"]) <= 0:
                raise ValueError
        except ValueError:
            message = "PLC Timeout muss größer als 0 sein."
            self._plc_status.setText(message)
            self._plc_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "PLC-Konfiguration", message)
            return
        if len(values["PLC_SHIPPER_COUNTRY"]) != 2 or not values["PLC_SHIPPER_COUNTRY"].isalpha():
            message = "Absender Land muss ein ISO-2-Code sein, zum Beispiel AT."
            self._plc_status.setText(message)
            self._plc_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "PLC-Konfiguration", message)
            return
        if not (values["PLC_SHIPPER_PHONE"] or values["PLC_SHIPPER_EMAIL"]):
            message = "Für PLC-Zollsendungen ist beim Absender Telefon oder E-Mail erforderlich."
            self._plc_status.setText(message)
            self._plc_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "PLC-Konfiguration", message)
            return

        service: SecretService = self._container.resolve(SecretService)
        self._plc_status.setText("PLC-Konfiguration wird gespeichert...")

        def job() -> bool:
            for key in _PLC_SECRET_KEYS:
                service.save_secret(key, values[key])
            return True

        self._secret_worker = BackgroundWorker(job)
        self._secret_worker.signals.result.connect(self._on_plc_settings_saved)
        self._secret_worker.signals.error.connect(self._on_plc_settings_error)
        self._secret_worker.signals.finished.connect(lambda: setattr(self, "_secret_worker", None))
        self._secret_worker.start()

    def _on_plc_settings_saved(self, _payload: object) -> None:
        self._plc_status.setText("PLC-Konfiguration verschlüsselt gespeichert.")
        self._plc_status.setStyleSheet(_OK_STYLE)

    def _on_plc_settings_error(self, exc: Exception) -> None:
        self._plc_status.setText(f"Fehler: {exc}")
        self._plc_status.setStyleSheet(_ERR_STYLE)
        QMessageBox.warning(self, "PLC-Konfiguration", str(exc))

    def _save_tokens(self) -> None:
        if self._secret_worker is not None and self._secret_worker.isRunning():
            return
        service: SecretService = self._container.resolve(SecretService)
        extra_raw = self._extra_tokens_json.toPlainText().strip() or "{}"
        try:
            extra_obj = json.loads(extra_raw)
        except json.JSONDecodeError as exc:
            self._secret_status.setText(f"JSON-Fehler: {exc}")
            self._secret_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "JSON-Fehler", f"Ungueltiges Token-JSON:\n\n{exc}")
            return
        if not isinstance(extra_obj, dict):
            self._secret_status.setText("Formatfehler bei weiteren Tokens")
            self._secret_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "Formatfehler", "Weitere Tokens muessen ein JSON-Objekt sein.")
            return

        values = {
            "SEVDESK_API_TOKEN": self._inp_sevdesk.text(),
            "WIX_API_KEY": self._inp_wix.text(),
            "WIX_SITE_ID": self._inp_wix_site.text(),
            "WIX_ACCOUNT_ID": self._inp_wix_account.text(),
        }
        values.update(
            {
                key: str(extra_obj[key])
                for key in _EXTRA_SECRET_KEYS
                if extra_obj.get(key) is not None
            }
        )
        self._secret_status.setText("Tokens werden verschluesselt gespeichert...")

        def job() -> bool:
            for key, value in values.items():
                service.save_secret(key, value)
            return True

        self._secret_worker = BackgroundWorker(job)
        self._secret_worker.signals.result.connect(self._on_tokens_saved)
        self._secret_worker.signals.error.connect(self._on_tokens_save_error)
        self._secret_worker.signals.finished.connect(lambda: setattr(self, "_secret_worker", None))
        self._secret_worker.start()

    def _on_tokens_saved(self, _payload: object) -> None:
        self._secret_status.setText("Tokens verschluesselt gespeichert.")
        self._secret_status.setStyleSheet(_OK_STYLE)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Tokens wurden in der DB gespeichert", 4500)

    def _on_tokens_save_error(self, exc: Exception) -> None:
        self._secret_status.setText(f"Fehler: {exc}")
        self._secret_status.setStyleSheet(_ERR_STYLE)
        QMessageBox.warning(self, "Speichern fehlgeschlagen", str(exc))

    def _create_clickup_task(self) -> None:
        if self._clickup_worker is not None and self._clickup_worker.isRunning():
            return

        title = self._clickup_title.text().strip()
        list_id = self._clickup_list_id.text().strip()
        description = self._clickup_description.toPlainText().strip()
        client: ClickUpClient = self._container.resolve(ClickUpClient)

        if not client.has_credentials():
            self._clickup_status.setText("CLICKUP_API_TOKEN fehlt.")
            self._clickup_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "ClickUp", "Bitte zuerst CLICKUP_API_TOKEN speichern.")
            return
        if not list_id:
            self._clickup_status.setText("Listen-ID fehlt.")
            self._clickup_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "ClickUp", "Bitte eine ClickUp Listen-ID eintragen.")
            return
        if not title:
            self._clickup_status.setText("Titel fehlt.")
            self._clickup_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "ClickUp", "Bitte einen Titel fuer die Aufgabe eingeben.")
            return

        self._clickup_create_btn.setEnabled(False)
        self._clickup_status.setText("Erstelle Task...")
        self._clickup_status.setStyleSheet(_WARN_STYLE)

        def job() -> ClickUpTask:
            return client.create_task(title, description=description, list_id=list_id)

        self._clickup_worker = BackgroundWorker(job)
        self._clickup_worker.signals.result.connect(self._on_clickup_created)
        self._clickup_worker.signals.error.connect(self._on_clickup_error)
        self._clickup_worker.signals.finished.connect(self._on_clickup_finished)
        self._clickup_worker.start()

    def _on_clickup_created(self, task: object) -> None:
        if not isinstance(task, ClickUpTask):
            return
        self._set_setting_value(_CLICKUP_LIST_ID_KEY, self._clickup_list_id.text().strip())
        self._clickup_status.setText(f"Task erstellt: {task.name} ({task.id})")
        self._clickup_status.setStyleSheet(_OK_STYLE)
        self._clickup_title.clear()
        self._clickup_description.clear()
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("ClickUp-Task erstellt", 4000)

    def _on_clickup_error(self, exc: Exception) -> None:
        logger.error("ClickUp task creation failed: %s", exc)
        self._clickup_status.setText(f"Fehler: {exc}")
        self._clickup_status.setStyleSheet(_ERR_STYLE)
        QMessageBox.warning(self, "ClickUp", str(exc))

    def _on_clickup_finished(self) -> None:
        self._clickup_create_btn.setEnabled(True)
