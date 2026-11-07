"""Shared validate/hash/deduplicate/publish pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path

from xw_office.services.invoice_collection.domain import (
    DownloadedArtifact,
    SinkReceipt,
    ValidatedDocument,
    utc_now,
)
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.naming import build_relative_path
from xw_office.services.invoice_collection.pdf_validation import inspect_pdf
from xw_office.services.invoice_collection.ports import DocumentSink


@dataclass(frozen=True)
class PipelineResult:
    document: ValidatedDocument
    receipt: SinkReceipt


class DocumentPipeline:
    """Apply identical document handling to mail, API, browser and manual routes."""

    def __init__(self, *, sink: DocumentSink, journal: InvoiceJournal | None = None) -> None:
        self.sink = sink
        self.journal = journal

    def process(self, artifact: DownloadedArtifact) -> PipelineResult:
        inspection = inspect_pdf(artifact.path)
        digest = _sha256(artifact.path)
        candidate = artifact.candidate
        if self.journal is not None and candidate.external_id:
            previous = self.journal.has_external_id(
                connection_id=str(candidate.connection.connection_id),
                route_key=candidate.route_key,
                external_id=candidate.external_id,
            )
            if previous is not None and previous[0] != digest:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.CONTENT_CONFLICT,
                    "Externe Dokument-ID wurde bereits mit anderem Inhalt verarbeitet",
                )
        relative_path = build_relative_path(candidate, sha256=digest, fallback_date=date.today())
        document = ValidatedDocument(
            candidate=candidate,
            sha256=digest,
            size_bytes=inspection.size_bytes,
            page_count=inspection.page_count,
            relative_path=relative_path,
            validated_at=utc_now(),
        )
        receipt = self.sink.publish(document, artifact.path)
        if self.journal is not None:
            self.journal.record_document(document=document, sink_id=self.sink.sink_id, receipt=receipt)
        return PipelineResult(document=document, receipt=receipt)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
