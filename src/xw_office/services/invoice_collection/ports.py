"""Ports used to keep connectors, persistence and UI orchestration independent."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DownloadedArtifact,
    SinkReceipt,
    ValidatedDocument,
)


class CancelToken(Protocol):
    @property
    def cancelled(self) -> bool: ...


class InvoiceConnector(Protocol):
    route_key: str

    def discover(self) -> list[DocumentCandidate]: ...

    def download(
        self,
        candidate: DocumentCandidate,
        workspace: Path,
        cancel: CancelToken | None = None,
    ) -> DownloadedArtifact: ...


class DocumentSink(Protocol):
    sink_id: str

    def preflight(self) -> None: ...

    def publish(self, document: ValidatedDocument, source_path: Path) -> SinkReceipt: ...


class DocumentJournal(Protocol):
    def has_hash(self, *, tenant_id: str, sink_id: str, sha256: str) -> bool: ...

    def has_external_id(
        self,
        *,
        connection_id: str,
        route_key: str,
        external_id: str,
    ) -> tuple[str, str] | None: ...

    def record_document(
        self,
        *,
        document: ValidatedDocument,
        sink_id: str,
        receipt: SinkReceipt,
    ) -> None: ...
