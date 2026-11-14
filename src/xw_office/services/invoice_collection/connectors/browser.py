"""Generic headful browser connector with an injected session boundary."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DownloadedArtifact,
    ProviderConnection,
)
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
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

    def __init__(
        self,
        *,
        connection: ProviderConnection,
        session: BrowserInvoiceSession,
        start: date | None = None,
        end: date | None = None,
    ) -> None:
        self.connection = connection
        self.session = session
        self.start = start
        self.end = end

    def probe(self) -> bool:
        return bool(self.session.probe())

    def open_login(self) -> None:
        self.session.open_login()

    def resume_after_login(self) -> list[DocumentCandidate]:
        """Probe the same account and resume only this route after visible login."""
        if not self.probe():
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED,
                "Browserroute bleibt nach Anmeldung geschützt",
            )
        return self.discover()

    def discover(self) -> list[DocumentCandidate]:
        return [
            candidate
            for candidate in self.session.discover()
            if _in_period(candidate.document_date, self.start, self.end)
        ]

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

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()


def _in_period(value: date | None, start: date | None, end: date | None) -> bool:
    """Keep unknown portal dates for manual review, but enforce known bounds."""
    if value is None:
        return True
    return (start is None or value >= start) and (end is None or value <= end)
