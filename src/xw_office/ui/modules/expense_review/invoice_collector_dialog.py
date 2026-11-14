"""Provider-independent invoice collector dialog for the expense review module."""
from __future__ import annotations

from pathlib import Path
import calendar
from datetime import date, datetime
import re
import uuid
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from xw_office.core.app_paths import default_invoice_target_dir, find_repo_root
from xw_office.core.worker import BackgroundWorker
from xw_office.services.invoice_collection.connectors.manual_import import ManualImportConnector
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import (
    DateRange,
    DocumentType,
    ProviderConnection,
    RouteSettings,
    TenantId,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.bootstrap import build_connector_factories
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
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
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Rechnungen abrufen")
        self.resize(900, 560)
        self._settings = QSettings("XeisWorks", "XW Office")
        self._connection_repository = connection_repository or ConnectionRepository()
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
        self._mailbox.setPlaceholderText("Postfach für Lieferantenbelege")
        self._mailbox.setAccessibleName("Microsoft Graph Rechnungs-Postfach")
        self._sender_domains = QLineEdit()
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
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Provider/Konto", "Route", "Mandant", "Datei", "Ergebnis"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._load_catalog()
        self._provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()
        self._build_ui()
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
            return
        provider_id = str(self._provider.currentData() or "")
        provider = next(
            (item for item in catalog.providers if item.provider_id == provider_id), None
        )
        if provider is None:
            return
        for route in provider.routes:
            self._route.addItem(
                f"{route.route_key} ({route.method}, {route.maturity})", route
            )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder, stretch=1)
        choose = QPushButton("Ordner wählen")
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        root.addLayout(folder_row)
        form = QFormLayout()
        form.addRow("Mandant", self._tenant)
        form.addRow("Rechnungsdatum von", self._period_start)
        form.addRow("Rechnungsdatum bis", self._period_end)
        form.addRow("Provider", self._provider)
        form.addRow("Abrufroute", self._route)
        form.addRow("Kontoalias", self._account_alias)
        form.addRow("Graph-Mailbox", self._mailbox)
        form.addRow("Bestätigte Absenderdomains", self._sender_domains)
        form.addRow("Dokumenttyp", self._document_type)
        root.addLayout(form)
        actions = QHBoxLayout()
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

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "OneDrive-Business-Ordner auswählen")
        if selected:
            self._set_folder(Path(selected))

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
        connections = self._connection_repository.list_enabled()
        if not connections:
            self._status.setText(
                "Keine aktiven Provider-Verbindungen eingerichtet. "
                "Nutzen Sie zunächst „PDF manuell hinzufügen“."
            )
            return
        if not any(route.enabled for connection in connections for route in connection.route_settings):
            self._status.setText(
                "Keine aktivierte Abrufroute eingerichtet. Nicht live verifizierte Routen "
                "bleiben gesperrt; Belege können manuell hinzugefügt werden."
            )
            return
        service = self._collection_service
        if service is None:
            service = InvoiceCollectionService(
                connections=self._connection_repository,
                factories=build_connector_factories(),
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
        self._status.setText(f"{len(connections)} aktive Verbindung(en) werden abgerufen …")
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
            lambda: service.collect_active(cancel=worker, period=period)
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
        if route is None or route.method != "mail":
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
            "document_type": str(self._document_type.currentData().value),
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
            finally:
                close_method = getattr(connector, "close", None)
                if callable(close_method):
                    close_method()

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
        message = str(error)
        if "msal-extensions" in message:
            self._status.setText(
                "Geschützter Microsoft-Token-Cache fehlt. Installiere das optionale "
                "Paket xw-office[invoice-collection] und starte den Test erneut."
            )
        elif "keyring" in message:
            self._status.setText("Windows Credential Manager ist für diese Verbindung nicht verfügbar.")
        else:
            self._status.setText(f"Mailbox-Test fehlgeschlagen: {type(error).__name__}")

    def _on_mail_test_finished(self, worker: BackgroundWorker) -> None:
        if self._mail_test_worker is worker:
            self._mail_test_worker = None
        self._mail_test_button.setEnabled(True)

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
            )
        for issue in result.issues:
            self._append_collection_result(
                provider_id=issue.provider_id,
                account_alias=issue.account_alias,
                route_key=issue.route_key,
                tenant_id=issue.tenant_id,
                display_name=None,
                outcome=issue.message,
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
        ]
        for column, value in enumerate(values):
            self._table.setItem(row, column, QTableWidgetItem(value))

    def _on_collection_error(self, generation: int, error: Exception) -> None:
        if generation != self._fetch_generation:
            return
        self._status.setText(f"Abruf fehlgeschlagen: {error}")

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
        if selected_route.maturity != "verified":
            self._status.setText(
                "Diese Abrufroute ist noch nicht live verifiziert und kann nicht aktiviert werden. "
                "Nutzen Sie den manuellen PDF-Import."
            )
            return
        route_options = {"connector": str(selected_route.connector)}
        if selected_route.method == "mail":
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
        route_options["document_type"] = str(self._document_type.currentData().value)
        connection = ProviderConnection.create(
            provider_id=provider_id,
            tenant_id=TenantId(str(self._tenant.currentData())),
            account_alias=account_alias,
            route_settings=(
                RouteSettings(
                    route_key=str(selected_route.route_key),
                    options=route_options,
                ),
            ),
        )
        self._connection_repository.save(connection)
        self._status.setText("Verbindung lokal gespeichert; Secretwerte werden separat hinterlegt.")

    def _manual_import(self) -> None:
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        if not self._folder.text().strip():
            self._status.setText("Bitte zuerst einen Zielordner auswählen.")
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
            document_type = self._document_type.currentData()
            target_root = Path(self._folder.text())
            provider_id = str(self._provider.currentData() or "manual")
            tenant_id = str(self._tenant.currentData())
            worker: BackgroundWorker

            def import_files() -> list[tuple[str, str, str, str]]:
                return _run_manual_import(
                    files=selected_files,
                    connection=connection,
                    document_type=document_type,
                    target_root=target_root,
                    provider_id=provider_id,
                    tenant_id=tenant_id,
                    cancel=worker,
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
            self._append_result(
                str(filename),
                str(outcome),
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
        error_count = sum(
            str(row[3]).startswith("ERROR:")
            for row in result
            if isinstance(row, tuple) and len(row) == 4
        )
        self._status.setText(
            f"Import abgeschlossen: {new_count} neu, {existing_count} bereits vorhanden, "
            f"{review_count} zur Prüfung, {error_count} fehlgeschlagen. "
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


def _run_manual_import(
    *,
    files: list[Path],
    connection: ProviderConnection,
    document_type: DocumentType,
    target_root: Path,
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
        sink=OneDriveLocalSink(target_root), journal=InvoiceJournal()
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
