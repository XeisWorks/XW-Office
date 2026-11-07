"""Generic headful browser connector with an injected session boundary."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DownloadedArtifact,
    ProviderConnection,
)
from xw_office.services.invoice_collection.ports import CancelToken


class BrowserInvoiceSession(Protocol):
    def probe(self) -> bool: ...

    def open_login(self) -> None: ...

    def discover(self) -> list[DocumentCandidate]: ...

    def download(self, candidate: DocumentCandidate, destination: Path) -> None: ...


class BrowserInvoiceConnector:
    """Use a provider-specific session while keeping pipeline/orchestrator generic."""

    route_key = "billing_portal"

    def __init__(self, *, connection: ProviderConnection, session: BrowserInvoiceSession) -> None:
        self.connection = connection
        self.session = session

    def probe(self) -> bool:
        return bool(self.session.probe())

    def open_login(self) -> None:
        self.session.open_login()

    def discover(self) -> list[DocumentCandidate]:
        return list(self.session.discover())

    def download(
        self,
        candidate: DocumentCandidate,
        workspace: Path,
        cancel: CancelToken | None = None,
    ) -> DownloadedArtifact:
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Browser-Abruf abgebrochen")
        workspace.mkdir(parents=True, exist_ok=True)
        destination = workspace / candidate.original_filename
        self.session.download(candidate, destination)
        return DownloadedArtifact(candidate=candidate, path=destination)
