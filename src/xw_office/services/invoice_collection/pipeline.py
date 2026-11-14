"""Shared validate/hash/deduplicate/publish pipeline."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import shutil

from xw_office.services.invoice_collection.domain import (
    DateRange,
    DownloadedArtifact,
    SinkReceipt,
    ValidatedDocument,
    utc_now,
)
from xw_office.services.invoice_collection.errors import (
    DocumentValidationError,
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.invoice_date import extract_invoice_date_from_pdf
from xw_office.services.invoice_collection.naming import build_relative_path
from xw_office.services.invoice_collection.pdf_validation import inspect_pdf
from xw_office.services.invoice_collection.ports import DocumentSink
from xw_office.services.invoice_collection.security import ensure_invoice_collection_dirs


@dataclass(frozen=True)
class PipelineResult:
    document: ValidatedDocument
    receipt: SinkReceipt


class DocumentPipeline:
    """Apply identical document handling to mail, API, browser and manual routes."""

    def __init__(
        self,
        *,
        sink: DocumentSink,
        journal: InvoiceJournal | None = None,
        run_id: str | None = None,
        period: DateRange | None = None,
        quarantine_root: Path | None = None,
    ) -> None:
        self.sink = sink
        self.journal = journal
        self.run_id = run_id
        self.period = period
        self.quarantine_root = quarantine_root or ensure_invoice_collection_dirs()["quarantine"]

    def process(self, artifact: DownloadedArtifact) -> PipelineResult:
        try:
            inspection = inspect_pdf(artifact.path)
        except DocumentValidationError:
            self._quarantine(artifact.path)
            raise
        digest = _sha256(artifact.path)
        candidate = artifact.candidate
        review_reason: str | None = None
        document_date = candidate.document_date or extract_invoice_date_from_pdf(artifact.path)
        if document_date is None:
            review_reason = "Rechnungsdatum ungeklärt"
        elif self.period is not None and not (
            self.period.start <= document_date <= self.period.end
        ):
            raise InvoiceCollectionError(
                InvoiceErrorCode.OUT_OF_PERIOD,
                "Rechnungsdatum liegt außerhalb des gewählten Zeitraums",
            )
        candidate = replace(
            candidate,
            document_date=document_date,
            metadata={
                **candidate.metadata,
                **({"review_reason": review_reason} if review_reason else {}),
            },
        )
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
        relative_path = build_relative_path(candidate, sha256=digest)
        document = ValidatedDocument(
            candidate=candidate,
            sha256=digest,
            size_bytes=inspection.size_bytes,
            page_count=inspection.page_count,
            relative_path=relative_path,
            validated_at=utc_now(),
        )
        receipt = self.sink.publish(document, artifact.path)
        if review_reason:
            receipt = replace(receipt, review_reason=review_reason)
        if self.journal is not None:
            document_id = self.journal.record_document(
                document=document, sink_id=self.sink.sink_id, receipt=receipt
            )
            if self.run_id is not None:
                self.journal.link_document_to_run(run_id=self.run_id, document_id=document_id)
        return PipelineResult(document=document, receipt=receipt)

    def _quarantine(self, source_path: Path) -> None:
        if self.quarantine_root is None or not source_path.exists():
            return
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        name = source_path.name.replace("/", "_").replace("\\", "_")
        target = self.quarantine_root / name
        if target.exists():
            target = self.quarantine_root / (
                f"{source_path.stem}-{utc_now():%Y%m%d%H%M%S%f}{source_path.suffix}"
            )
        shutil.move(str(source_path), str(target))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
