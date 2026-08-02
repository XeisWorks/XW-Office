"""XW-Copilot panel for Outlook add-in integration and text blocks."""
from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService
from xw_office.services.xw_copilot.contracts import XWCopilotResponse
from xw_office.services.xw_copilot.ingress import XWCopilotIngress
from xw_office.services.xw_copilot.service import AuditEntry, XWCopilotConfig, XWCopilotService
from xw_office.ui.widgets.data_table import DataTable

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)


class XWCopilotView(QWidget):
    """Manage Outlook add-in settings and reusable copilot blocks."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: XWCopilotService = container.resolve(XWCopilotService)
        self._dry_run_service: XWCopilotDryRunService = container.resolve(XWCopilotDryRunService)
        self._ingress: XWCopilotIngress = container.resolve(XWCopilotIngress)
        self._io_worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        tabs = QTabWidget()
        tabs.addTab(self._build_settings_tab(), "Einstellungen")
        tabs.addTab(self._build_templates_tab(), "Bausteine")
        tabs.addTab(self._build_dry_run_tab(), "Dry-Run")
        tabs.addTab(self._build_history_tab(), "Verlauf")
        tabs.addTab(self._build_notes_tab(), "Integration")
        root.addWidget(tabs)

        self._settings_status.setText("Konfiguration wird geladen...")
        self._templates_status.setText("Bausteine werden geladen...")
        self._history_status.setText("Verlauf wird geladen...")
        self._load_initial_data()
        self._ingress.signals.request_received.connect(self._on_ingress_request_received)

    def _load_initial_data(self) -> None:
        def job() -> tuple[XWCopilotConfig, list[dict[str, str]], list[AuditEntry]]:
            return (
                self._service.load_config(),
                self._service.load_templates(),
                self._service.load_audit_entries(),
            )

        self._start_io(job, self._on_initial_data)

    def _on_initial_data(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        config, templates, entries = payload
        if isinstance(config, XWCopilotConfig):
            self._apply_config(config)
        if isinstance(templates, list):
            self._apply_templates(templates)
        if isinstance(entries, list):
            self._apply_history(entries)

    def _start_io(
        self,
        job: Callable[[], Any],
        on_result: Callable[[object], None],
        on_error_status: QLabel | None = None,
    ) -> bool:
        if self._io_worker is not None and self._io_worker.isRunning():
            return False
        self._io_worker = BackgroundWorker(job)
        self._io_worker.signals.result.connect(on_result)
        self._io_worker.signals.error.connect(
            lambda exc: self._on_io_error(exc, on_error_status)
        )
        self._io_worker.signals.finished.connect(self._on_io_finished)
        self._io_worker.start()
        return True

    def _on_io_finished(self) -> None:
        self._io_worker = None

    def _on_io_error(self, exc: Exception, status: QLabel | None) -> None:
        if status is not None:
            status.setText(f"Fehler: {exc}")
        logger.warning("XW-Copilot background I/O failed: %s", exc)

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        group = QGroupBox("Outlook Add-in Konfiguration")
        form = QFormLayout(group)

        self._enabled = QCheckBox("XW-Copilot aktiv")
        form.addRow("Status:", self._enabled)

        self._mode = QComboBox()
        self._mode.addItems(["dry_run", "live"])
        form.addRow("Modus:", self._mode)

        self._tenant_id = QLineEdit()
        self._tenant_id.setPlaceholderText("Azure Tenant ID")
        form.addRow("Tenant ID:", self._tenant_id)

        self._client_id = QLineEdit()
        self._client_id.setPlaceholderText("App Client ID")
        form.addRow("Client ID:", self._client_id)

        self._mailbox = QLineEdit()
        self._mailbox.setPlaceholderText("z. B. info@xeisworks.at")
        form.addRow("Mailbox:", self._mailbox)

        self._webhook = QLineEdit()
        self._webhook.setPlaceholderText("Webhook URL (optional)")
        form.addRow("Webhook:", self._webhook)

        self._project = QLineEdit()
        self._project.setPlaceholderText("Standardprojekt / Board")
        form.addRow("Default Projekt:", self._project)

        self._allowed_ips = QLineEdit()
        self._allowed_ips.setPlaceholderText("Kommagetrennte IPs, leer = alle")
        form.addRow("IP-Allowlist:", self._allowed_ips)

        self._settings_status = QLabel("-")
        form.addRow("Config Status:", self._settings_status)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Laden")
        load_btn.clicked.connect(self._load_config_into_form)
        btn_row.addWidget(load_btn)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save_config_from_form)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

        lay.addWidget(group)

        ingress_group = QGroupBox("Lokaler HTTP-Ingress (optional)")
        ingress_form = QFormLayout(ingress_group)

        self._ingress_port = QSpinBox()
        self._ingress_port.setRange(1024, 65535)
        self._ingress_port.setValue(8765)
        ingress_form.addRow("Port:", self._ingress_port)

        self._ingress_secret = QLineEdit()
        self._ingress_secret.setPlaceholderText("HMAC-Secret (leer = keine Signaturpruefung)")
        self._ingress_secret.setEchoMode(QLineEdit.EchoMode.Password)
        ingress_form.addRow("HMAC-Secret:", self._ingress_secret)

        self._ingress_status = QLabel("Gestoppt")
        ingress_form.addRow("Status:", self._ingress_status)

        ingress_btn_row = QHBoxLayout()
        self._ingress_start_btn = QPushButton("Starten")
        self._ingress_start_btn.clicked.connect(self._start_ingress)
        ingress_btn_row.addWidget(self._ingress_start_btn)
        self._ingress_stop_btn = QPushButton("Stoppen")
        self._ingress_stop_btn.clicked.connect(self._stop_ingress)
        self._ingress_stop_btn.setEnabled(False)
        ingress_btn_row.addWidget(self._ingress_stop_btn)
        ingress_btn_row.addStretch()
        ingress_form.addRow("", ingress_btn_row)

        lay.addWidget(ingress_group)
        lay.addStretch()
        return page

    def _build_templates_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Prompt-/Mail-Bausteine als JSON-Liste (name/kind/content)."))

        self._templates_editor = QPlainTextEdit()
        self._templates_editor.setPlaceholderText(
            '[{"name": "Antwort - Rechnung", "kind": "mail", "content": "Vielen Dank ..."}]'
        )
        lay.addWidget(self._templates_editor, stretch=1)

        row = QHBoxLayout()
        load_btn = QPushButton("Bausteine laden")
        load_btn.clicked.connect(self._load_templates_into_editor)
        row.addWidget(load_btn)
        save_btn = QPushButton("Bausteine speichern")
        save_btn.clicked.connect(self._save_templates_from_editor)
        row.addWidget(save_btn)
        row.addStretch()
        lay.addLayout(row)

        self._templates_status = QLabel("-")
        lay.addWidget(self._templates_status)

        render_group = QGroupBox("Vorschau mit Variablen")
        render_lay = QVBoxLayout(render_group)
        render_lay.addWidget(QLabel('Variablen als JSON-Objekt, z. B. {"kunde": "...", "datum": "..."}'))
        self._render_vars = QLineEdit()
        self._render_vars.setPlaceholderText('{"kunde": "Max Mustermann", "datum": "2025-01-01"}')
        render_lay.addWidget(self._render_vars)
        render_btn = QPushButton("Ersten Baustein rendern")
        render_btn.clicked.connect(self._render_first_template)
        render_lay.addWidget(render_btn)
        self._render_output = QPlainTextEdit()
        self._render_output.setReadOnly(True)
        self._render_output.setMaximumHeight(140)
        render_lay.addWidget(self._render_output)
        lay.addWidget(render_group)
        return page

    def _build_notes_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(
            "XW-Copilot Integrationshinweise:\n\n"
            "1) Outlook Add-in spricht per Webhook/API mit XW-Office.\n"
            "2) Modus dry_run: nur Vorschau/Logging, keine Live-Aktionen.\n"
            "3) Modus live: Aktionen gegen produktive Endpunkte aktiv.\n"
            "4) Bausteine werden zentral in DB gehalten (mehrere PCs).\n"
            "5) Tokens weiterhin ueber Settings/SecretService pflegen."
        )
        lay.addWidget(txt)

        schema_group = QGroupBox("JSON Schema Export")
        schema_lay = QHBoxLayout(schema_group)
        schema_lay.addWidget(QLabel("XWCopilotRequest Schema exportieren:"))
        export_btn = QPushButton("Schema exportieren ...")
        export_btn.clicked.connect(self._export_schema)
        schema_lay.addWidget(export_btn)
        schema_lay.addStretch()
        lay.addWidget(schema_group)
        return page

    def _build_dry_run_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(
            QLabel(
                "Dry-Run Contract Test: Request JSON einfuegen, validieren und Vorschauantwort erzeugen."
            )
        )

        self._dry_run_request = QPlainTextEdit()
        self._dry_run_request.setPlaceholderText("Request JSON")
        self._dry_run_request.setPlainText(
            json.dumps(
                {
                    "tenant": "xeisworks",
                    "mailbox": "info@xeisworks.at",
                    "action": "crm.lookup_contact",
                    "payload_version": "1.0",
                    "payload": {"query": "Musterkunde"},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        lay.addWidget(self._dry_run_request, stretch=1)

        row = QHBoxLayout()
        execute_btn = QPushButton("Dry-Run ausfuehren")
        execute_btn.clicked.connect(self._execute_dry_run)
        row.addWidget(execute_btn)
        reset_btn = QPushButton("Beispiel laden")
        reset_btn.clicked.connect(self._reset_dry_run_sample)
        row.addWidget(reset_btn)
        row.addStretch()
        lay.addLayout(row)

        self._dry_run_status = QLabel("-")
        lay.addWidget(self._dry_run_status)

        self._dry_run_response = QPlainTextEdit()
        self._dry_run_response.setReadOnly(True)
        self._dry_run_response.setPlaceholderText("Response JSON")
        lay.addWidget(self._dry_run_response, stretch=1)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        cols = ["Zeit", "Action", "Modus", "OK?", "Correlation-ID"]
        self._history_table = DataTable(cols)
        self._history_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self._history_table, stretch=1)

        row = QHBoxLayout()
        reload_btn = QPushButton("Verlauf laden")
        reload_btn.clicked.connect(self._reload_history)
        row.addWidget(reload_btn)
        clear_btn = QPushButton("Verlauf loeschen")
        clear_btn.clicked.connect(self._clear_history)
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)

        self._history_status = QLabel("-")
        lay.addWidget(self._history_status)
        return page

    def _load_config_into_form(self) -> None:
        self._settings_status.setText("Konfiguration wird geladen...")
        self._start_io(self._service.load_config, self._on_config_loaded, self._settings_status)

    def _on_config_loaded(self, payload: object) -> None:
        if isinstance(payload, XWCopilotConfig):
            self._apply_config(payload)

    def _apply_config(self, cfg: XWCopilotConfig) -> None:
        self._enabled.setChecked(cfg.enabled)
        mode_idx = self._mode.findText(cfg.mode)
        self._mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self._tenant_id.setText(cfg.outlook_tenant_id)
        self._client_id.setText(cfg.outlook_client_id)
        self._mailbox.setText(cfg.mailbox_address)
        self._webhook.setText(cfg.webhook_url)
        self._project.setText(cfg.default_project)
        self._allowed_ips.setText(cfg.allowed_ips)
        self._settings_status.setText("Konfiguration geladen")

    def _save_config_from_form(self) -> None:
        if not self._service.has_storage():
            QMessageBox.warning(self, "XW-Copilot", "Kein DB-Storage verfuegbar (DATABASE_URL fehlt).")
            return
        cfg = XWCopilotConfig(
            enabled=self._enabled.isChecked(),
            mode=self._mode.currentText(),
            outlook_tenant_id=self._tenant_id.text().strip(),
            outlook_client_id=self._client_id.text().strip(),
            mailbox_address=self._mailbox.text().strip(),
            webhook_url=self._webhook.text().strip(),
            default_project=self._project.text().strip(),
            allowed_ips=self._allowed_ips.text().strip(),
        )
        self._settings_status.setText("Konfiguration wird gespeichert...")

        def job() -> XWCopilotConfig:
            self._service.save_config(cfg)
            return cfg

        self._start_io(job, self._on_config_saved, self._settings_status)

    def _on_config_saved(self, payload: object) -> None:
        if not isinstance(payload, XWCopilotConfig):
            return
        self._settings_status.setText("Konfiguration gespeichert")
        QMessageBox.information(self, "XW-Copilot", "Einstellungen gespeichert.")

    def _load_templates_into_editor(self) -> None:
        self._templates_status.setText("Bausteine werden geladen...")
        self._start_io(self._service.load_templates, self._on_templates_loaded, self._templates_status)

    def _on_templates_loaded(self, payload: object) -> None:
        if isinstance(payload, list):
            self._apply_templates(payload)

    def _apply_templates(self, rows: list[object]) -> None:
        self._templates_editor.setPlainText(json.dumps(rows, ensure_ascii=False, indent=2))
        self._templates_status.setText(f"{len(rows)} Bausteine geladen")

    def _save_templates_from_editor(self) -> None:
        if not self._service.has_storage():
            QMessageBox.warning(self, "XW-Copilot", "Kein DB-Storage verfuegbar (DATABASE_URL fehlt).")
            return
        raw = self._templates_editor.toPlainText().strip() or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "XW-Copilot", f"Ungueltiges JSON: {exc}")
            return
        if not isinstance(data, list):
            QMessageBox.warning(self, "XW-Copilot", "Erwartet wird ein JSON-Array aus Objekten.")
            return
        rows: list[dict[str, str]] = [
            {str(key): str(value) for key, value in row.items()}
            for row in data
            if isinstance(row, dict)
        ]
        self._templates_status.setText("Bausteine werden gespeichert...")

        def job() -> list[dict[str, str]]:
            self._service.save_templates(rows)
            return rows

        self._start_io(job, self._on_templates_saved, self._templates_status)

    def _on_templates_saved(self, payload: object) -> None:
        rows = payload if isinstance(payload, list) else []
        self._templates_status.setText(f"{len(rows)} Bausteine gespeichert")
        QMessageBox.information(self, "XW-Copilot", "Bausteine gespeichert.")

    def _execute_dry_run(self) -> None:
        raw = self._dry_run_request.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "XW-Copilot", "Bitte ein Request JSON eingeben.")
            return
        self._dry_run_status.setText("Dry-Run wird ausgefuehrt...")
        self._start_io(
            lambda: self._dry_run_service.simulate_raw_request(raw),
            self._on_dry_run_result,
            self._dry_run_status,
        )

    def _on_dry_run_result(self, payload: object) -> None:
        if not isinstance(payload, XWCopilotResponse):
            self._dry_run_status.setText("Keine gueltige Dry-Run-Antwort")
            return
        result = payload
        self._dry_run_response.setPlainText(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        if result.accepted:
            self._dry_run_status.setText(
                f"OK: action={result.action}, mode={result.mode}, correlation_id={result.correlation_id}"
            )
        else:
            self._dry_run_status.setText(
                f"Fehler: action={result.action}, correlation_id={result.correlation_id}"
            )

    def _reset_dry_run_sample(self) -> None:
        self._dry_run_request.setPlainText(
            json.dumps(
                {
                    "tenant": "xeisworks",
                    "mailbox": "info@xeisworks.at",
                    "action": "crm.lookup_contact",
                    "payload_version": "1.0",
                    "payload": {"query": "Musterkunde"},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        self._dry_run_status.setText("Beispiel-Request geladen")

    def _reload_history(self) -> None:
        self._history_status.setText("Verlauf wird geladen...")
        self._start_io(self._service.load_audit_entries, self._on_history_loaded, self._history_status)

    def _on_history_loaded(self, payload: object) -> None:
        entries = payload if isinstance(payload, list) else []
        self._apply_history(entries)

    def _apply_history(self, entries: list[object]) -> None:
        rows = [
            {
                "Zeit": entry.timestamp,
                "Action": entry.action,
                "Modus": entry.mode,
                "OK?": "Ja" if entry.accepted else "Nein",
                "Correlation-ID": entry.correlation_id,
                "__sort__OK?": 1 if entry.accepted else 0,
                "__entry__": entry,
            }
            for entry in entries
            if isinstance(entry, AuditEntry)
        ]
        self._history_table.set_data(rows)
        self._history_status.setText(f"{len(rows)} Eintraege geladen")

    def _clear_history(self) -> None:
        if not self._service.has_storage():
            QMessageBox.warning(self, "XW-Copilot", "Kein DB-Storage verfuegbar.")
            return
        self._history_status.setText("Verlauf wird geloescht...")

        def job() -> bool:
            self._service.clear_audit_log()
            return True

        self._start_io(job, self._on_history_cleared, self._history_status)

    def _on_history_cleared(self, _payload: object) -> None:
        self._history_table.set_data([])
        self._history_status.setText("Verlauf geloescht")

    def _start_ingress(self) -> None:
        port = self._ingress_port.value()
        secret = self._ingress_secret.text().strip()
        self._ingress.update_secret(secret)
        try:
            self._ingress.start(port=port)
        except OSError as exc:
            QMessageBox.warning(self, "Ingress", f"Port {port} nicht verfuegbar: {exc}")
            return
        self._ingress_status.setText(f"Laeuft auf 127.0.0.1:{port}")
        self._ingress_start_btn.setEnabled(False)
        self._ingress_stop_btn.setEnabled(True)

    def _stop_ingress(self) -> None:
        self._ingress.stop()
        self._ingress_status.setText("Gestoppt")
        self._ingress_start_btn.setEnabled(True)
        self._ingress_stop_btn.setEnabled(False)

    def _on_ingress_request_received(self, action: str, correlation_id: str, accepted: bool) -> None:
        self._reload_history()
        status = "OK" if accepted else "Fehler"
        self._history_status.setText(f"Eingehend: {status} - action={action} corr={correlation_id}")

    def _render_first_template(self) -> None:
        raw = self._templates_editor.toPlainText().strip() or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._render_output.setPlainText(f"Ungueltiges JSON: {exc}")
            return
        if not isinstance(data, list) or not data:
            self._render_output.setPlainText("Keine Bausteine vorhanden.")
            return

        first = data[0] if isinstance(data[0], dict) else {}
        content = str(first.get("content") or "")
        vars_raw = self._render_vars.text().strip() or "{}"
        try:
            variables_raw = json.loads(vars_raw)
        except json.JSONDecodeError as exc:
            self._render_output.setPlainText(f"Variablen-JSON ungueltig: {exc}")
            return
        if not isinstance(variables_raw, dict):
            self._render_output.setPlainText("Variablen muessen ein JSON-Objekt sein.")
            return
        variables = {str(key): str(value) for key, value in variables_raw.items()}
        rendered = self._service.render_template(content, variables)
        self._render_output.setPlainText(rendered)

    def _export_schema(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Schema exportieren",
            "xw_copilot_request_schema.json",
            "JSON (*.json)",
        )
        if not path_str:
            return
        target = Path(path_str)

        def job() -> str:
            self._service.export_request_schema(target)
            return str(target)

        self._start_io(
            job,
            self._on_schema_exported,
        )

    def _on_schema_exported(self, payload: object) -> None:
        QMessageBox.information(self, "Schema", f"Exportiert nach:\n{payload}")
