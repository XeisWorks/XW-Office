"""Provider-independent invoice collector dialog for the expense review module."""
from __future__ import annotations

from pathlib import Path
import uuid

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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

from xw_office.core.app_paths import find_repo_root
from xw_office.core.worker import BackgroundWorker
from xw_office.services.invoice_collection.connectors.manual_import import ManualImportConnector
from xw_office.services.invoice_collection.connections import ConnectionRepository
from xw_office.services.invoice_collection.domain import (
    DocumentType,
    ProviderConnection,
    RouteSettings,
    TenantId,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.factories import ConnectorFactoryRegistry
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
        self._document_type = QComboBox()
        for item in DocumentType:
            self._document_type.addItem(item.value, item)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Provider", "Mandant", "Datei", "Ergebnis"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._load_catalog()
        self._provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()
        self._build_ui()
        saved = str(self._settings.value("invoice_collection/target_folder") or "").strip()
        if saved:
            self._set_folder(Path(saved))

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
        form.addRow("Provider", self._provider)
        form.addRow("Abrufroute", self._route)
        form.addRow("Kontoalias", self._account_alias)
        form.addRow("Dokumenttyp", self._document_type)
        root.addLayout(form)
        actions = QHBoxLayout()
        self._fetch_button = QPushButton("Alle aktiven Verbindungen abrufen")
        self._fetch_button.clicked.connect(self._fetch_active)
        actions.addWidget(self._fetch_button)
        save = QPushButton("Verbindung speichern")
        save.clicked.connect(self._save_connection)
        actions.addWidget(save)
        manual = QPushButton("PDF manuell hinzufügen")
        manual.clicked.connect(self._manual_import)
        actions.addWidget(manual)
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
        service = self._collection_service
        if service is None:
            service = InvoiceCollectionService(
                connections=self._connection_repository,
                factories=ConnectorFactoryRegistry(),
                target_root=Path(self._folder.text()),
                journal=InvoiceJournal(),
            )
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self._fetch_button.setEnabled(False)
        self._status.setText(f"{len(connections)} aktive Verbindung(en) werden abgerufen …")
        worker = BackgroundWorker(service.collect_active)
        self._fetch_worker = worker
        worker.signals.result.connect(self._on_collection_finished)
        worker.signals.error.connect(self._on_collection_error)
        worker.signals.finished.connect(lambda: self._fetch_button.setEnabled(True))
        worker.start()

    def _on_collection_finished(self, result: object) -> None:
        if not isinstance(result, CollectionRun):
            self._status.setText("Abruf lieferte ein ungültiges Ergebnis.")
            return
        issue_count = len(result.issues)
        self._status.setText(
            f"Abruf beendet: {result.summary.new_count} neu, "
            f"{result.summary.existing_count} bereits vorhanden, {issue_count} Route(n) offen."
        )

    def _on_collection_error(self, error: Exception) -> None:
        self._status.setText(f"Abruf fehlgeschlagen: {error}")

    def _save_connection(self) -> None:
        provider_id = str(self._provider.currentData() or "").strip()
        account_alias = self._account_alias.text().strip()
        if not provider_id or not account_alias:
            self._status.setText("Provider und Kontoalias müssen ausgefüllt sein.")
            return
        connection = ProviderConnection.create(
            provider_id=provider_id,
            tenant_id=TenantId(str(self._tenant.currentData())),
            account_alias=account_alias,
            route_settings=(
                RouteSettings(
                    route_key=str(self._route.currentData().route_key),
                    options={"connector": str(self._route.currentData().connector)},
                ),
            )
            if self._route.currentData() is not None
            else (),
        )
        self._connection_repository.save(connection)
        self._status.setText("Verbindung lokal gespeichert; Secretwerte werden separat hinterlegt.")

    def _manual_import(self) -> None:
        if not self._folder.text().strip():
            self._status.setText("Bitte zuerst einen Zielordner auswählen.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "PDF-Belege auswählen", filter="PDF-Dateien (*.pdf)"
        )
        if not files:
            return
        try:
            connection = ProviderConnection.create(
                provider_id=str(self._provider.currentData() or "manual"),
                tenant_id=TenantId(str(self._tenant.currentData())),
                account_alias="manual",
            )
            connector = ManualImportConnector(
                connection=connection,
                files=[Path(item) for item in files],
                document_type=self._document_type.currentData(),
            )
            sink = OneDriveLocalSink(Path(self._folder.text()))
            pipeline = DocumentPipeline(sink=sink, journal=InvoiceJournal())
            workspace = ensure_invoice_collection_dirs()["tmp"] / str(uuid.uuid4())
            workspace.mkdir(parents=True, exist_ok=True)
            try:
                for candidate in connector.discover():
                    artifact = connector.download(candidate, workspace)
                    result = pipeline.process(artifact)
                    self._append_result(candidate.original_filename, result.receipt.outcome.value)
            finally:
                for child in workspace.glob("*"):
                    child.unlink(missing_ok=True)
                workspace.rmdir()
            self._status.setText(
                "Import abgeschlossen; lokale Dateien sind als SYNC_PENDING markiert."
            )
        except Exception as exc:  # noqa: BLE001 - show safe local setup/import error
            self._status.setText(f"Import fehlgeschlagen: {exc}")

    def _append_result(self, filename: str, outcome: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        values = [
            str(self._provider.currentData() or "manual"),
            str(self._tenant.currentData()),
            filename,
            outcome,
        ]
        for column, value in enumerate(values):
            self._table.setItem(row, column, QTableWidgetItem(value))
