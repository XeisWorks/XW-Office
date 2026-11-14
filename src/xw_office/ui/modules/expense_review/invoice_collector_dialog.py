"""Provider-independent invoice collector dialog for the expense review module."""
from __future__ import annotations

from pathlib import Path
import calendar
from datetime import date, datetime
import ipaddress
import re
import uuid
from collections.abc import Callable
from typing import TypeVar
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QSettings, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from xw_office.core.app_paths import default_invoice_target_dir, find_repo_root
from xw_office.core.worker import BackgroundWorker
from xw_office.services.invoice_collection.auth.secrets import KeyringSecretStore, SecretStore
from xw_office.services.invoice_collection.connectors.manual_import import ManualImportConnector
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import (
    DateRange,
    DocumentType,
    ProviderConnection,
    RouteSettings,
    TenantId,
)
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.bootstrap import build_connector_factories
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
from xw_office.services.invoice_collection.ports import CancelToken
from xw_office.services.invoice_collection.registry import ProviderCatalog
from xw_office.services.invoice_collection.security import ensure_invoice_collection_dirs
from xw_office.services.invoice_collection.service import InvoiceCollectionService, CollectionRun
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink


class InvoiceCollectorDialog(QDialog):
    """Small first-slice dialog; provider-specific actions come from capabilities later."""

    def __init__(
        self,
        *,
        tenant_id: str,
        parent: object | None = None,
        connection_repository: ConnectionRepository | None = None,
        collection_service: InvoiceCollectionService | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Rechnungen abrufen")
        self.resize(900, 560)
        self._settings = QSettings("XeisWorks", "XW Office")
        self._connection_repository = connection_repository or ConnectionRepository()
        self._secret_store = secret_store
        self._editing_connection: ProviderConnection | None = None
        self._saved_connections_by_id: dict[str, ProviderConnection] = {}
        self._collection_service = collection_service
        self._fetch_worker: BackgroundWorker | None = None
        self._mail_test_worker: BackgroundWorker | None = None
        self._manual_worker: BackgroundWorker | None = None
        self._fetch_generation = 0
        self._folder = QLineEdit()
        self._folder.setReadOnly(True)
        self._folder.setAccessibleName("OneDrive-Zielordner")
        self._status = QLabel("Bitte einen OneDrive-Zielordner auswählen.")
        self._status.setWordWrap(True)
        self._tenant = QComboBox()
        self._tenant.addItem("XeisWorks", TenantId.XW.value)
        self._tenant.addItem("WüdaraMusi", TenantId.WUEDARA.value)
        index = self._tenant.findData(tenant_id)
        if index >= 0:
            self._tenant.setCurrentIndex(index)
        self._provider = QComboBox()
        self._route = QComboBox()
        self._account_alias = QLineEdit("default")
        self._account_alias.setAccessibleName("Kontoalias")
        self._mailbox = QLineEdit()
        self._mailbox_label = QLabel("Graph-Mailbox")
        self._mailbox.setPlaceholderText("Postfach für Lieferantenbelege")
        self._mailbox.setAccessibleName("Microsoft Graph Rechnungs-Postfach")
        self._sender_domains = QLineEdit()
        self._sender_domains_label = QLabel("Bestätigte Absenderdomains")
        self._sender_domains.setPlaceholderText("Nur bestätigte Domains, kommasepariert")
        self._sender_domains.setAccessibleName("Bestätigte Rechnungs-Absenderdomains")
        now = datetime.now(ZoneInfo("Europe/Vienna")).date()
        month_start = now.replace(day=1)
        month_end = now.replace(day=calendar.monthrange(now.year, now.month)[1])
        self._period_start = _date_edit(month_start)
        self._period_end = _date_edit(month_end)
        self._document_type = QComboBox()
        for item in DocumentType:
            self._document_type.addItem(item.value, item)
        self._api_token_label = QLabel("API-Zugang")
        self._api_token = QLineEdit()
        self._api_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_token.setPlaceholderText("Nur lokal im Windows Credential Manager")
        self._api_token_label.setVisible(False)
        self._api_token.setVisible(False)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Provider/Konto", "Route", "Mandant", "Datei", "Ergebnis", "Belegquellen"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._load_catalog()
        self._provider.currentIndexChanged.connect(self._provider_changed)
        self._route.currentIndexChanged.connect(self._route_changed)
        self._provider_changed()
        self._build_ui()
        self._provider_changed()
        self._route_changed()
        self._load_saved_connections()
        saved = str(self._settings.value("invoice_collection/target_folder") or "").strip()
        if saved:
            self._set_folder(Path(saved))
        else:
            default_target = default_invoice_target_dir()
            if default_target.is_dir() and _is_writable_directory(default_target):
                self._set_folder(default_target)
            else:
                self._folder.setText(str(default_target))

    def _load_catalog(self) -> None:
        path = (
            find_repo_root()
            / "markdowns"
            / "rechnungsautomat_ausgabenpruefung_2026-11"
            / "PROVIDER_REGISTRY.yaml"
        )
        try:
            catalog = ProviderCatalog.from_yaml(path)
        except Exception as exc:  # noqa: BLE001 - surface safe setup error in the dialog
            self._status.setText(f"Provider-Registry konnte nicht geladen werden: {exc}")
            return
        for provider in catalog.providers:
            self._provider.addItem(provider.label, provider.provider_id)
        self._catalog = catalog

    def _provider_changed(self) -> None:
        self._route.clear()
        catalog = getattr(self, "_catalog", None)
        if catalog is None:
            self._update_provider_portals(())
            return
        provider_id = str(self._provider.currentData() or "")
        provider = next(
            (item for item in catalog.providers if item.provider_id == provider_id), None
        )
        if provider is None:
            self._update_provider_portals(())
            return
        self._update_provider_portals(provider.portal_hosts)
        for route in provider.routes:
            self._route.addItem(
                f"{route.route_key} ({route.method}, {route.maturity})", route
            )
        self._route_changed()

    def _route_changed(self, *_args: object) -> None:
        route = self._route.currentData()
        capabilities = route.capabilities if route is not None else None
        mail_test_button = getattr(self, "_mail_test_button", None)
        if mail_test_button is not None:
            mail_test_button.setEnabled(
                capabilities is not None
                and capabilities.mailbox_probe
                and not (
                    self._mail_test_worker is not None
                    and self._mail_test_worker.isRunning()
                )
            )
        self._api_token.clear()
        visible = capabilities is not None and capabilities.protected_credential
        self._api_token_label.setVisible(visible)
        self._api_token.setVisible(visible)
        self._mailbox.setVisible(bool(capabilities and capabilities.mailbox_probe))
        self._sender_domains.setVisible(bool(capabilities and capabilities.mailbox_probe))
        self._mailbox_label.setVisible(bool(capabilities and capabilities.mailbox_probe))
        self._sender_domains_label.setVisible(bool(capabilities and capabilities.mailbox_probe))
        scope = route.required_scope if route is not None else None
        self._api_token_label.setText(
            f"API-Zugang ({scope})" if scope else "API-Zugang"
        )
        existing_setting = next(
            (
                setting
                for setting in (
                    self._editing_connection.route_settings
                    if self._editing_connection is not None
                    else ()
                )
                if route is not None and setting.route_key == route.route_key
            ),
            None,
        )
        self._api_token.setPlaceholderText(
            "Zugang hinterlegt; leer lassen zum Beibehalten"
            if existing_setting is not None and existing_setting.secret_ref
            else (
                f"Credential mit {scope} lokal hinterlegen"
                if scope
                else "Route-spezifisches Credential lokal hinterlegen"
            )
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder, stretch=1)
        choose = QPushButton("Ordner wählen")
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        open_folder = QPushButton("Ordner öffnen")
        open_folder.clicked.connect(self._open_folder)
        folder_row.addWidget(open_folder)
        self._review_folder_button = QPushButton("Prüfablage öffnen")
        self._review_folder_button.clicked.connect(self._open_review_folder)
        folder_row.addWidget(self._review_folder_button)
        root.addLayout(folder_row)
        form = QFormLayout()
        self._saved_connections = QComboBox()
        self._saved_connections.currentIndexChanged.connect(self._saved_connection_changed)
        form.addRow("Gespeicherte Verbindung", self._saved_connections)
        form.addRow("Mandant", self._tenant)
        form.addRow("Rechnungsdatum von", self._period_start)
        form.addRow("Rechnungsdatum bis", self._period_end)
        form.addRow("Provider", self._provider)
        form.addRow("Abrufroute", self._route)
        form.addRow("Kontoalias", self._account_alias)
        form.addRow(self._mailbox_label, self._mailbox)
        form.addRow(self._sender_domains_label, self._sender_domains)
        form.addRow("Dokumenttyp", self._document_type)
        form.addRow(self._api_token_label, self._api_token)
        root.addLayout(form)
        actions = QHBoxLayout()
        self._portal_menu = QMenu(self)
        self._portal_button = QPushButton("Portal öffnen")
        self._portal_button.setMenu(self._portal_menu)
        self._portal_button.setEnabled(False)
        actions.addWidget(self._portal_button)
        self._fetch_button = QPushButton("Alle aktiven Verbindungen abrufen")
        self._fetch_button.clicked.connect(self._fetch_active)
        actions.addWidget(self._fetch_button)
        self._cancel_button = QPushButton("Abruf abbrechen")
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._cancel_fetch)
        actions.addWidget(self._cancel_button)
        save = QPushButton("Verbindung speichern")
        save.clicked.connect(self._save_connection)
        actions.addWidget(save)
        self._connection_toggle_button = QPushButton("Verbindung deaktivieren")
        self._connection_toggle_button.setEnabled(False)
        self._connection_toggle_button.clicked.connect(self._toggle_saved_connection)
        actions.addWidget(self._connection_toggle_button)
        self._mail_test_button = QPushButton("Graph-Mailbox testen")
        self._mail_test_button.clicked.connect(self._test_mailbox_access)
        actions.addWidget(self._mail_test_button)
        self._manual_button = QPushButton("PDF manuell hinzufügen")
        self._manual_button.clicked.connect(self._manual_import)
        actions.addWidget(self._manual_button)
        self._manual_cancel_button = QPushButton("Import abbrechen")
        self._manual_cancel_button.setEnabled(False)
        self._manual_cancel_button.clicked.connect(self._cancel_manual_import)
        actions.addWidget(self._manual_cancel_button)
        actions.addStretch()
        root.addLayout(actions)
        root.addWidget(self._status)
        root.addWidget(self._table, stretch=1)
        close = QPushButton("Schließen")
        close.clicked.connect(self.reject)
        root.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _update_provider_portals(self, hosts: tuple[str, ...]) -> None:
        menu = getattr(self, "_portal_menu", None)
        button = getattr(self, "_portal_button", None)
        if menu is None or button is None:
            return
        menu.clear()
        for host in hosts:
            action = menu.addAction(host)
            action.triggered.connect(
                lambda _checked=False, current_host=host: self._open_provider_portal(
                    current_host
                )
            )
        button.setEnabled(bool(hosts))

    def _open_provider_portal(self, host: str) -> None:
        url = _provider_portal_url(host)
        if url is None:
            self._status.setText("Das Provider-Portalziel ist ungültig und wurde nicht geöffnet.")
            return
        if not QDesktopServices.openUrl(url):
            self._status.setText("Das Provider-Portal konnte nicht geöffnet werden.")
            return
        self._status.setText(
            "Provider-Website geöffnet. Anmeldung und Belegdownload bleiben manuell; "
            "der OneDrive-Cloudstatus wird dadurch nicht bestätigt."
        )

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "OneDrive-Business-Ordner auswählen")
        if selected:
            self._set_folder(Path(selected))

    def _open_folder(self) -> None:
        target = Path(self._folder.text().strip()).expanduser()
        if not target.is_dir():
            self._status.setText("Der ausgewählte Zielordner ist nicht verfügbar.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve()))):
            self._status.setText("Der Zielordner konnte nicht geöffnet werden.")
            return
        self._status.setText(
            "OneDrive-Ordner geöffnet. Der Cloud-Syncstatus wird dadurch nicht bestätigt."
        )

    def _open_review_folder(self) -> None:
        folder_text = self._folder.text().strip()
        if not folder_text:
            self._status.setText("Bitte zuerst einen Zielordner auswählen.")
            return
        target_root = Path(folder_text).expanduser()
        tenant_id = str(self._tenant.currentData() or "")
        if tenant_id not in {tenant.value for tenant in TenantId}:
            self._status.setText("Der ausgewählte Mandant ist ungültig.")
            return
        root = target_root.resolve(strict=False)
        review_folder = (root / tenant_id / "_needs_review").resolve(strict=False)
        try:
            review_folder.relative_to(root)
        except ValueError:
            self._status.setText("Die Prüfablage liegt außerhalb des Zielordners.")
            return
        if not review_folder.is_dir():
            self._status.setText("Für diesen Mandanten ist noch keine Prüfablage vorhanden.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(review_folder))):
            self._status.setText("Die Prüfablage konnte nicht geöffnet werden.")
            return
        self._status.setText(
            "Prüfablage geöffnet. Datum und Belegart müssen manuell geprüft werden; "
            "der Cloud-Syncstatus wird dadurch nicht bestätigt."
        )

    def _load_saved_connections(self, *, select_id: str | None = None) -> None:
        connections, _issues = self._connection_repository.list_all_with_issues()
        self._saved_connections.blockSignals(True)
        self._saved_connections.clear()
        self._saved_connections.addItem("Neue Verbindung", "")
        self._saved_connections_by_id = {}
        for connection in connections:
            connection_id = str(connection.connection_id)
            state = "aktiv" if connection.enabled else "deaktiviert"
            label = (
                f"{connection.provider_id} / {connection.account_alias} "
                f"({connection.tenant_id.value}, {state})"
            )
            self._saved_connections.addItem(label, connection_id)
            self._saved_connections_by_id[connection_id] = connection
        index = self._saved_connections.findData(select_id or "")
        self._saved_connections.setCurrentIndex(max(index, 0))
        self._saved_connections.blockSignals(False)
        self._saved_connection_changed(self._saved_connections.currentIndex())

    def _saved_connection_changed(self, index: int) -> None:
        connection_id = str(self._saved_connections.itemData(index) or "")
        self._editing_connection = self._saved_connections_by_id.get(connection_id)
        if self._editing_connection is None:
            self._provider.setEnabled(True)
            self._tenant.setEnabled(True)
            self._account_alias.setText("default")
            self._mailbox.clear()
            self._sender_domains.clear()
            self._api_token.clear()
            self._connection_toggle_button.setEnabled(False)
            self._route_changed()
            return

        connection = self._editing_connection
        self._provider.setEnabled(False)
        self._tenant.setEnabled(False)
        self._provider.setCurrentIndex(self._provider.findData(connection.provider_id))
        self._tenant.setCurrentIndex(self._tenant.findData(connection.tenant_id.value))
        self._account_alias.setText(connection.account_alias)
        route_settings = connection.route_settings[0] if connection.route_settings else None
        if route_settings is not None:
            route_index = next(
                (
                    i for i in range(self._route.count())
                    if (route := self._route.itemData(i)) is not None
                    and route.route_key == route_settings.route_key
                ),
                -1,
            )
            if route_index >= 0:
                self._route.setCurrentIndex(route_index)
            options = route_settings.options
            self._mailbox.setText(options.get("mailbox", ""))
            self._sender_domains.setText(options.get("sender_domains", ""))
            type_index = next(
                (
                    i for i in range(self._document_type.count())
                    if (document_type := self._document_type.itemData(i)) is not None
                    and str(getattr(document_type, "value", document_type))
                    == options.get("document_type")
                ),
                -1,
            )
            if type_index >= 0:
                self._document_type.setCurrentIndex(type_index)
        self._route_changed()
        self._connection_toggle_button.setText(
            "Verbindung deaktivieren" if connection.enabled else "Verbindung aktivieren"
        )
        self._connection_toggle_button.setEnabled(True)

    def _toggle_saved_connection(self) -> None:
        connection = self._editing_connection
        if connection is None:
            return
        enabled = not connection.enabled
        if enabled:
            catalog = getattr(self, "_catalog", None)
            if catalog is None:
                self._status.setText(
                    "Die Verbindung kann erst aktiviert werden, wenn alle aktiven Routen live verifiziert sind."
                )
                return
            for settings in connection.route_settings:
                if not settings.enabled:
                    continue
                route = catalog.route(connection.provider_id, settings.route_key)
                if route is None or route.maturity != "verified":
                    self._status.setText(
                        "Die Verbindung kann erst aktiviert werden, wenn alle aktiven Routen live verifiziert sind."
                    )
                    return
                if route.capabilities.protected_credential:
                    try:
                        if not settings.secret_ref:
                            raise ValueError("missing secret reference")
                        self._secret_store_for_ui().get(settings.secret_ref)
                    except Exception:  # noqa: BLE001 - never expose keyring/provider details
                        self._status.setText(
                            "Für diese API-Route fehlt ein Zugang im geschützten lokalen Speicher."
                        )
                        return
        if self._connection_repository.set_enabled(connection.connection_id, enabled):
            self._load_saved_connections(select_id=str(connection.connection_id))
            self._status.setText(
                "Verbindung aktiviert." if enabled else "Verbindung deaktiviert."
            )

    def _set_folder(self, path: Path) -> None:
        self._folder.setText(str(path))
        self._settings.setValue("invoice_collection/target_folder", str(path))
        self._status.setText("OneDrive-Ordner ausgewählt; Cloudstatus wird erst remote bestätigt.")

    def _fetch_active(self) -> None:
        if self._manual_worker is not None and self._manual_worker.isRunning():
            return
        if not self._folder.text().strip():
            self._status.setText("Bitte zuerst einen Zielordner auswählen.")
            return
        connections, invalid_records = self._connection_repository.list_enabled_with_issues()
        if not connections and not invalid_records:
            self._status.setText(
                "Keine aktiven Provider-Verbindungen eingerichtet. "
                "Nutzen Sie zunächst „PDF manuell hinzufügen“."
            )
            return
        if not any(route.enabled for connection in connections for route in connection.route_settings) and not invalid_records:
            self._status.setText(
                "Keine aktivierte Abrufroute eingerichtet. Nicht live verifizierte Routen "
                "bleiben gesperrt; Belege können manuell hinzugefügt werden."
            )
            return
        service = self._collection_service
        if service is None:
            service = InvoiceCollectionService(
                connections=self._connection_repository,
                factories=build_connector_factories(
                    secret_store_factory=self._secret_store_for_ui
                ),
                target_root=Path(self._folder.text()),
                journal=InvoiceJournal(),
                catalog=getattr(self, "_catalog", None),
            )
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self._fetch_generation += 1
        generation = self._fetch_generation
        self._fetch_button.setEnabled(False)
        self._manual_button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._status.setText(
            f"{len(connections)} aktive Verbindung(en), "
            f"{len(invalid_records)} fehlerhafte Konfiguration(en) werden geprüft …"
        )
        try:
            period = self._selected_period()
        except ValueError:
            self._fetch_button.setEnabled(True)
            self._manual_button.setEnabled(True)
            self._cancel_button.setEnabled(False)
            self._status.setText("Das Enddatum muss am oder nach dem Startdatum liegen.")
            return
        # The closure is evaluated only after the worker has started, so the
        # worker itself can serve as the cooperative CancelToken.
        worker: BackgroundWorker
        worker = BackgroundWorker(
            lambda: _collect_active_safely(service, cancel=worker, period=period)
        )
        self._fetch_worker = worker
        worker.signals.result.connect(
            lambda result, token=generation: self._on_collection_finished(token, result)
        )
        worker.signals.error.connect(
            lambda error, token=generation: self._on_collection_error(token, error)
        )
        worker.signals.finished.connect(
            lambda token=generation, current=worker: self._on_fetch_finished(token, current)
        )
        worker.start()

    def _test_mailbox_access(self) -> None:
        route = self._route.currentData()
        mailbox = self._mailbox.text().strip()
        domains = _parse_sender_domains(self._sender_domains.text())
        if route is None or not route.capabilities.mailbox_probe:
            self._status.setText("Bitte zuerst eine Mailroute auswählen.")
            return
        if not _looks_like_mailbox(mailbox) or not domains:
            self._status.setText(
                "Bitte Rechnungs-Postfach und bestätigte Absenderdomains eintragen."
            )
            return
        if self._mail_test_worker is not None and self._mail_test_worker.isRunning():
            return
        options = {
            "connector": str(route.connector),
            "mailbox": mailbox,
            "sender_domains": ",".join(sorted(domains)),
            "document_type": self._selected_document_type().value,
        }
        connection = ProviderConnection.create(
            provider_id=str(self._provider.currentData()),
            tenant_id=TenantId(str(self._tenant.currentData())),
            account_alias=self._account_alias.text().strip() or "mailbox-test",
            route_settings=(RouteSettings(route_key=route.route_key, options=options),),
        )
        factories = build_connector_factories()
        try:
            connector = factories.create(str(route.connector), connection, connection.route_settings[0])
        except Exception as exc:  # noqa: BLE001 - show safe configuration failure
            self._status.setText(f"Mailbox-Test nicht vorbereitet: {type(exc).__name__}")
            return
        self._mail_test_button.setEnabled(False)
        self._status.setText(
            "Microsoft-Anmeldung wird geöffnet. Nach Zustimmung prüfe ich nur den Mailboxzugriff."
        )

        def probe() -> bool:
            try:
                probe_method = getattr(connector, "probe", None)
                if not callable(probe_method):
                    raise RuntimeError("Mailbox-Probe wird vom Connector nicht unterstützt")
                probe_method()
                return True
            except Exception as exc:  # noqa: BLE001 - keep provider details out of worker logs
                raise _safe_collector_error(exc) from None
            finally:
                close_method = getattr(connector, "close", None)
                if callable(close_method):
                    try:
                        close_method()
                    except Exception as exc:  # noqa: BLE001 - cleanup errors can contain URLs
                        raise _safe_collector_error(exc) from None

        worker = BackgroundWorker(probe)
        self._mail_test_worker = worker
        worker.signals.result.connect(self._on_mail_test_result)
        worker.signals.error.connect(self._on_mail_test_error)
        worker.signals.finished.connect(lambda current=worker: self._on_mail_test_finished(current))
        worker.start()

    def _on_mail_test_result(self, result: object) -> None:
        if result is True:
            self._status.setText(
                "Mailboxzugriff bestätigt. Dieser Probe markiert keine Rechnungsroute als verified."
            )

    def _on_mail_test_error(self, error: Exception) -> None:
        safe_error = _safe_collector_error(error)
        if safe_error.code is InvoiceErrorCode.CONFIGURATION_ERROR:
            self._status.setText(
                "Mailbox-Test nicht eingerichtet. Prüfe die optionale MSAL-/DPAPI-Laufzeit "
                "und das Paket xw-office[invoice-collection]."
            )
        else:
            self._status.setText(
                f"Mailbox-Test fehlgeschlagen ({safe_error.code.value}): {safe_error}"
            )

    def _on_mail_test_finished(self, worker: BackgroundWorker) -> None:
        if self._mail_test_worker is worker:
            self._mail_test_worker = None
        self._route_changed()

    def _cancel_fetch(self) -> None:
        worker = self._fetch_worker
        if worker is not None and worker.isRunning():
            self._fetch_generation += 1
            worker.cancel()
            self._status.setText("Abruf wird abgebrochen â€¦")
            self._cancel_button.setEnabled(False)

    def _selected_period(self) -> DateRange:
        start = date.fromisoformat(self._period_start.date().toString("yyyy-MM-dd"))
        end = date.fromisoformat(self._period_end.date().toString("yyyy-MM-dd"))
        return DateRange(start=start, end=end)

    def _selected_document_type(self) -> DocumentType:
        value = self._document_type.currentData()
        if isinstance(value, DocumentType):
            return value
        return DocumentType(str(value))

    def _secret_store_for_ui(self) -> SecretStore:
        if self._secret_store is None:
            self._secret_store = KeyringSecretStore()
        return self._secret_store

    def _on_collection_finished(self, generation: int, result: object) -> None:
        if generation != self._fetch_generation:
            return
        if not isinstance(result, CollectionRun):
            self._status.setText("Abruf lieferte ein ungültiges Ergebnis.")
            return
        issue_count = len(result.issues)
        error_count = result.summary.error_count
        successful_count = result.summary.new_count + result.summary.existing_count
        self._table.setRowCount(0)
        for item in result.summary.items:
            if item.error:
                outcome = (
                    "Außerhalb des gewählten Zeitraums"
                    if item.error.startswith("OUT_OF_PERIOD:")
                    else item.error
                )
            elif item.review_reason:
                outcome = f"NEEDS_REVIEW: {item.review_reason}"
            elif item.outcome is not None:
                outcome = item.outcome.value
            else:
                outcome = "Keine passenden Dokumente"
            self._append_collection_result(
                provider_id=item.provider_id,
                account_alias=item.account_alias,
                route_key=item.route_key,
                tenant_id=item.tenant_id,
                display_name=item.display_name,
                outcome=outcome,
                provenance=item.provenance,
            )
        for issue in result.issues:
            self._append_collection_result(
                provider_id=issue.provider_id,
                account_alias=issue.account_alias,
                route_key=issue.route_key,
                tenant_id=issue.tenant_id,
                display_name=None,
                outcome=issue.message,
                provenance=(),
            )
        if successful_count == 0 and (issue_count or error_count):
            self._status.setText(
                f"Kein Dokument verarbeitet. {issue_count + error_count} Route(n) "
                "konnten nicht ausgeführt werden. Details stehen in der Ergebnistabelle."
            )
            return
        if successful_count == 0:
            prefix = "Lauf fortgesetzt" if result.resumed else "Abruf abgeschlossen"
            out_of_period = result.summary.out_of_period_count
            filtered = f" {out_of_period} Dokument(e) lagen außerhalb des Zeitraums." if out_of_period else ""
            self._status.setText(
                f"{prefix}; keine passenden Dokumente gefunden.{filtered}"
            )
            return
        prefix = "Lauf fortgesetzt" if result.resumed else "Abruf beendet"
        self._status.setText(
            f"{prefix}: {result.summary.new_count} neu, "
            f"{result.summary.existing_count} bereits vorhanden, "
            f"{result.summary.review_count} zur Prüfung, "
            f"{result.summary.out_of_period_count} außerhalb Zeitraum, "
            f"{issue_count + error_count} Route(n) fehlgeschlagen. "
            "Lokal gespeicherte Dateien bleiben SYNC_PENDING."
        )

    def _append_collection_result(
        self,
        *,
        provider_id: str | None,
        account_alias: str | None,
        route_key: str | None,
        tenant_id: str | None,
        display_name: str | None,
        outcome: str,
        provenance: tuple[str, ...] = (),
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        provider_account = provider_id or "—"
        if account_alias:
            provider_account = f"{provider_account} / {account_alias}"
        values = [
            provider_account,
            route_key or "—",
            tenant_id or "—",
            display_name or "—",
            outcome,
            " · ".join(provenance) if provenance else "—",
        ]
        for column, value in enumerate(values):
            self._table.setItem(row, column, QTableWidgetItem(value))

    def _on_collection_error(self, generation: int, error: Exception) -> None:
        if generation != self._fetch_generation:
            return
        safe_error = _safe_collector_error(error)
        self._status.setText(
            f"Abruf fehlgeschlagen ({safe_error.code.value}): {safe_error}"
        )

    def _on_fetch_finished(self, generation: int, worker: BackgroundWorker) -> None:
        if self._fetch_worker is worker:
            self._fetch_worker = None
        if generation != self._fetch_generation:
            return
        self._fetch_button.setEnabled(True)
        self._manual_button.setEnabled(self._manual_worker is None)
        self._cancel_button.setEnabled(False)
        if worker.cancelled:
            self._status.setText("Abruf abgebrochen; bereits gespeicherte Dokumente bleiben erhalten.")

    def closeEvent(self, event: object) -> None:
        self._cancel_fetch()
        if self._mail_test_worker is not None and self._mail_test_worker.isRunning():
            self._mail_test_worker.cancel()
        self._cancel_manual_import()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _save_connection(self) -> None:
        provider_id = str(self._provider.currentData() or "").strip()
        account_alias = self._account_alias.text().strip()
        if not provider_id or not account_alias:
            self._status.setText("Provider und Kontoalias müssen ausgefüllt sein.")
            return
        selected_route = self._route.currentData()
        if selected_route is None:
            self._status.setText(
                "Für diesen Provider ist noch keine automatisierte Route verfügbar. "
                "Sie können Belege über den manuellen PDF-Import ablegen."
            )
            return
        route_verified = selected_route.maturity == "verified"
        route_options = {"connector": str(selected_route.connector)}
        if selected_route.capabilities.mailbox_probe:
            mailbox = self._mailbox.text().strip()
            domains = _parse_sender_domains(self._sender_domains.text())
            if not _looks_like_mailbox(mailbox) or not domains:
                self._status.setText(
                    "Für Mailabruf müssen ein Rechnungs-Postfach und mindestens eine "
                    "bestätigte Absenderdomain eingetragen sein."
                )
                return
            route_options.update(
                {
                    "mailbox": mailbox,
                    "sender_domains": ",".join(sorted(domains)),
                }
            )
        route_options["document_type"] = self._selected_document_type().value
        connection_id = (
            self._editing_connection.connection_id
            if self._editing_connection is not None
            else uuid.uuid4()
        )
        route_settings_by_key = {
            setting.route_key: setting
            for setting in (
                self._editing_connection.route_settings
                if self._editing_connection is not None
                else ()
            )
        }
        previous_setting = route_settings_by_key.get(str(selected_route.route_key))
        secret_ref = previous_setting.secret_ref if previous_setting is not None else None
        credential_ready = True
        if selected_route.capabilities.protected_credential:
            api_token = self._api_token.text().strip()
            if api_token:
                secret_ref = secret_ref or (
                    f"invoice-collection:{connection_id}:{selected_route.route_key}"
                )
                try:
                    self._secret_store_for_ui().set(secret_ref, api_token)
                except Exception as exc:  # noqa: BLE001 - do not surface secret-bearing errors
                    self._status.setText(
                        f"API-Zugang konnte nicht geschützt gespeichert werden: {type(exc).__name__}."
                    )
                    return
            elif secret_ref:
                try:
                    self._secret_store_for_ui().get(secret_ref)
                except Exception:  # noqa: BLE001 - keep disabled if secret cannot be read
                    credential_ready = False
            else:
                credential_ready = False
        route_settings_by_key[str(selected_route.route_key)] = RouteSettings(
            route_key=str(selected_route.route_key),
            options=route_options,
            secret_ref=secret_ref,
        )
        connection = ProviderConnection(
            connection_id=connection_id,
            provider_id=provider_id,
            tenant_id=TenantId(str(self._tenant.currentData())),
            account_alias=account_alias,
            enabled=(
                route_verified
                and credential_ready
                and (
                    self._editing_connection.enabled
                    if self._editing_connection is not None
                    else True
                )
            ),
            route_settings=tuple(route_settings_by_key.values()),
        )
        self._connection_repository.save(connection)
        self._api_token.clear()
        self._load_saved_connections(select_id=str(connection.connection_id))
        if not route_verified:
            self._status.setText(
                "Verbindung als deaktivierter Entwurf gespeichert. Aktivierung erst nach "
                "Live-Verifikation der Route; Secretwerte werden separat hinterlegt."
            )
        elif not credential_ready:
            self._status.setText(
                "Verbindung gespeichert und deaktiviert; für die API-Route fehlt ein geschützter Zugang."
            )
        elif not connection.enabled:
            self._status.setText(
                "Verbindung lokal gespeichert und deaktiviert; Secretwerte werden separat hinterlegt."
            )
        else:
            self._status.setText(
                "Verbindung lokal gespeichert; Secretwerte werden separat hinterlegt."
            )

    def _manual_import(self) -> None:
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        if not self._folder.text().strip():
            self._status.setText("Bitte zuerst einen Zielordner auswählen.")
            return
        try:
            period = self._selected_period()
        except ValueError:
            self._status.setText("Das Enddatum muss am oder nach dem Startdatum liegen.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "PDF-Belege auswählen", filter="PDF-Dateien (*.pdf)"
        )
        if not files:
            return
        if self._manual_worker is not None and self._manual_worker.isRunning():
            return
        try:
            connection = ProviderConnection.create(
                provider_id=str(self._provider.currentData() or "manual"),
                tenant_id=TenantId(str(self._tenant.currentData())),
                account_alias="manual",
            )
            selected_files = [Path(item) for item in files]
            document_type = self._selected_document_type()
            target_root = Path(self._folder.text())
            provider_id = str(self._provider.currentData() or "manual")
            tenant_id = str(self._tenant.currentData())
            worker: BackgroundWorker

            def import_files() -> list[tuple[str, str, str, str]]:
                return _run_collector_operation_safely(
                    lambda: _run_manual_import(
                        files=selected_files,
                        connection=connection,
                        document_type=document_type,
                        target_root=target_root,
                        period=period,
                        provider_id=provider_id,
                        tenant_id=tenant_id,
                        cancel=worker,
                    )
                )

            worker = BackgroundWorker(import_files, publish_result_on_cancel=True)
            self._manual_worker = worker
            worker.signals.result.connect(self._on_manual_import_result)
            worker.signals.error.connect(self._on_manual_import_error)
            worker.signals.finished.connect(
                lambda current=worker: self._on_manual_import_finished(current)
            )
            self._fetch_button.setEnabled(False)
            self._manual_button.setEnabled(False)
            self._manual_cancel_button.setEnabled(True)
            self._status.setText(f"{len(selected_files)} PDF-Datei(en) werden geprüft …")
            worker.start()
        except Exception as exc:  # noqa: BLE001 - show safe local setup/import error
            self._status.setText(f"Import konnte nicht gestartet werden: {type(exc).__name__}")

    def _on_manual_import_result(self, result: object) -> None:
        if not isinstance(result, list):
            self._status.setText("Import lieferte ein ungültiges Ergebnis.")
            return
        for row in result:
            if not isinstance(row, tuple) or len(row) != 4:
                continue
            provider_id, tenant_id, filename, outcome = row
            display_outcome = (
                "Außerhalb des gewählten Zeitraums"
                if outcome == InvoiceErrorCode.OUT_OF_PERIOD.value
                else str(outcome)
            )
            self._append_result(
                str(filename),
                display_outcome,
                provider_id=str(provider_id),
                tenant_id=str(tenant_id),
            )
        new_count = sum(row[3] == "NEW" for row in result if isinstance(row, tuple) and len(row) == 4)
        existing_count = sum(
            row[3] == "ALREADY_PRESENT"
            for row in result
            if isinstance(row, tuple) and len(row) == 4
        )
        review_count = sum(
            str(row[3]).startswith("NEEDS_REVIEW:")
            for row in result
            if isinstance(row, tuple) and len(row) == 4
        )
        out_of_period_count = sum(
            row[3] == InvoiceErrorCode.OUT_OF_PERIOD.value
            for row in result
            if isinstance(row, tuple) and len(row) == 4
        )
        error_count = sum(
            str(row[3]).startswith("ERROR:")
            for row in result
            if isinstance(row, tuple) and len(row) == 4
        )
        self._status.setText(
            f"Import abgeschlossen: {new_count} neu, {existing_count} bereits vorhanden, "
            f"{review_count} zur Prüfung, {out_of_period_count} außerhalb Zeitraum, "
            f"{error_count} fehlgeschlagen. "
            "Lokal gespeicherte Dateien bleiben SYNC_PENDING."
        )

    def _on_manual_import_error(self, error: Exception) -> None:
        self._status.setText(f"Import fehlgeschlagen: {type(error).__name__}")

    def _on_manual_import_finished(self, worker: BackgroundWorker) -> None:
        if self._manual_worker is worker:
            self._manual_worker = None
        self._manual_cancel_button.setEnabled(False)
        if self._fetch_worker is None:
            self._fetch_button.setEnabled(True)
            self._manual_button.setEnabled(True)
        if worker.cancelled:
            self._status.setText(
                "Import abgebrochen; bereits gespeicherte Dokumente bleiben erhalten."
            )

    def _cancel_manual_import(self) -> None:
        worker = self._manual_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self._manual_cancel_button.setEnabled(False)
            self._status.setText("Import wird abgebrochen …")

    def _append_result(
        self,
        filename: str,
        outcome: str,
        *,
        provider_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        values = [
            provider_id or str(self._provider.currentData() or "manual"),
            "manual_import",
            tenant_id or str(self._tenant.currentData()),
            filename,
            outcome,
        ]
        for column, value in enumerate(values):
            self._table.setItem(row, column, QTableWidgetItem(value))


_ResultT = TypeVar("_ResultT")


def _run_collector_operation_safely(operation: Callable[[], _ResultT]) -> _ResultT:
    """Convert unexpected failures before the generic worker logs them."""
    try:
        return operation()
    except Exception as exc:  # noqa: BLE001 - exceptions may contain secrets or signed URLs
        raise _safe_collector_error(exc) from None


def _collect_active_safely(
    service: InvoiceCollectionService,
    *,
    cancel: CancelToken,
    period: DateRange,
) -> CollectionRun:
    """Convert fatal collection failures before the generic worker logs them."""
    return _run_collector_operation_safely(
        lambda: service.collect_active(cancel=cancel, period=period)
    )


def _safe_collector_error(error: Exception) -> InvoiceCollectionError:
    """Preserve a stable error code while replacing untrusted exception text."""
    code = (
        error.code
        if isinstance(error, InvoiceCollectionError)
        else InvoiceErrorCode.INTERNAL_ERROR
    )
    message = {
        InvoiceErrorCode.CONFIGURATION_ERROR: "Lokale Collector-Konfiguration ist unvollständig",
        InvoiceErrorCode.DESTINATION_UNAVAILABLE: "Der ausgewählte Zielordner ist nicht verfügbar",
        InvoiceErrorCode.AUTH_REQUIRED: "Anmeldung oder Zustimmung ist erforderlich",
        InvoiceErrorCode.RATE_LIMITED: "Der Anbieter begrenzt Anfragen; bitte später erneut versuchen",
        InvoiceErrorCode.TRANSIENT_NETWORK: "Der Anbieter ist vorübergehend nicht erreichbar",
        InvoiceErrorCode.POLICY_BLOCKED: "Die Anbieterregel blockiert diesen Zugriff",
    }.get(code, "Der Vorgang konnte nicht sicher abgeschlossen werden")
    return InvoiceCollectionError(code, message)


def _provider_portal_url(host: str) -> QUrl | None:
    normalized = host.strip().casefold()
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(normalized) > 253 or not re.fullmatch(rf"{label}(?:\.{label})+", normalized):
        return None
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        return None
    url = QUrl(f"https://{normalized}/")
    if (
        not url.isValid()
        or url.scheme() != "https"
        or url.host().casefold() != normalized
        or url.userInfo()
        or url.port(-1) != -1
    ):
        return None
    return url


def _run_manual_import(
    *,
    files: list[Path],
    connection: ProviderConnection,
    document_type: DocumentType,
    target_root: Path,
    period: DateRange,
    provider_id: str,
    tenant_id: str,
    cancel: BackgroundWorker,
) -> list[tuple[str, str, str, str]]:
    """Validate and publish selected PDFs off the UI thread, returning display-only rows."""
    connector = ManualImportConnector(
        connection=connection,
        files=files,
        document_type=document_type,
    )
    pipeline = DocumentPipeline(
        sink=OneDriveLocalSink(target_root), journal=InvoiceJournal(), period=period
    )
    workspace = ensure_invoice_collection_dirs()["tmp"] / str(uuid.uuid4())
    workspace.mkdir(parents=True, exist_ok=False)
    results: list[tuple[str, str, str, str]] = []
    try:
        for candidate in connector.discover():
            if cancel.cancelled:
                break
            try:
                artifact = connector.download(candidate, workspace, cancel)
                result = pipeline.process(artifact)
                outcome = (
                    f"NEEDS_REVIEW: {result.receipt.review_reason}"
                    if result.receipt.review_reason
                    else result.receipt.outcome.value
                )
            except InvoiceCollectionError as exc:
                outcome = (
                    f"{exc.code.value}: {exc}"
                    if exc.code is InvoiceErrorCode.QUARANTINED
                    else exc.code.value
                )
            except Exception as exc:  # noqa: BLE001 - keep a failed file local to its row
                outcome = f"ERROR: {type(exc).__name__}"
            results.append(
                (provider_id, tenant_id, candidate.original_filename, outcome)
            )
        return results
    finally:
        for child in workspace.iterdir():
            if child.is_dir():
                raise RuntimeError("manual import workspace contains an unexpected directory")
            child.unlink(missing_ok=True)
        workspace.rmdir()


def _is_writable_directory(path: Path) -> bool:
    """Check the selected target without creating probe files in OneDrive."""
    try:
        return path.is_dir() and bool(path.stat().st_mode & 0o200)
    except OSError:
        return False


def _date_edit(value: date) -> QDateEdit:
    edit = QDateEdit(QDate(value.year, value.month, value.day))
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    return edit


def _looks_like_mailbox(value: str) -> bool:
    local, separator, domain = value.partition("@")
    return bool(separator and local and "." in domain and not any(ch.isspace() for ch in value))


def _parse_sender_domains(value: str) -> frozenset[str]:
    domains = {part.strip().casefold().lstrip("@") for part in value.split(",")}
    domains.discard("")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", item) for item in domains):
        return frozenset()
    return frozenset(domains)
