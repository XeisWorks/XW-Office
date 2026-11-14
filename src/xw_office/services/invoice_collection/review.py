"""Explicit, no-clobber resolution of PDFs archived for manual review."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
from uuid import UUID

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    ProviderConnection,
    SyncStatus,
    TenantId,
    ValidatedDocument,
    utc_now,
)
from xw_office.services.invoice_collection.errors import (
    DocumentValidationError,
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.journal import InvoiceJournal, ReviewDocument
from xw_office.services.invoice_collection.naming import build_relative_path
from xw_office.services.invoice_collection.pdf_validation import inspect_pdf
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink


@dataclass(frozen=True)
class ReviewResolutionResult:
    document: ReviewDocument
    resolved_path: Path
    sync_status: SyncStatus
    review_copy_removed: bool


class InvoiceReviewService:
    """Move a manually classified review PDF into its date-based archive location."""

    def __init__(self, *, journal: InvoiceJournal, sink: OneDriveLocalSink) -> None:
        self.journal = journal
        self.sink = sink

    def resolve(
        self,
        *,
        document: ReviewDocument,
        document_date: date,
        document_type: DocumentType,
    ) -> ReviewResolutionResult:
        if document_type is DocumentType.UNKNOWN:
            raise ValueError("a reviewed document needs a known document type")
        if document.sink_id != self.sink.sink_id:
            raise ValueError("review document belongs to another archive sink")
        current = self.journal.review_document_by_path(
            tenant_id=document.tenant_id,
            sink_id=document.sink_id,
            relative_path=document.relative_path,
        )
        if current != document:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONTENT_CONFLICT,
                "Review-Journaleintrag ist nicht mehr aktuell",
            )
        source_path = self.sink.target_path_for(document.relative_path)
        if not source_path.is_file():
            raise InvoiceCollectionError(
                InvoiceErrorCode.DESTINATION_UNAVAILABLE,
                "Review-PDF ist im gewählten Zielordner nicht verfügbar",
            )
        try:
            inspection = inspect_pdf(source_path)
        except DocumentValidationError:
            raise
        digest = _sha256(source_path)
        if digest != document.sha256:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONTENT_CONFLICT,
                "Review-PDF stimmt nicht mehr mit dem Journaleintrag überein",
            )
        candidate = DocumentCandidate(
            connection=_review_connection(document),
            route_key=document.route_key,
            source_id=f"review-resolution:{document.document_id}",
            external_id=None,
            document_type=document_type,
            original_filename=source_path.name,
            document_date=document_date,
        )
        relative_path = build_relative_path(candidate, sha256=digest)
        validated = ValidatedDocument(
            candidate=candidate,
            sha256=digest,
            size_bytes=inspection.size_bytes,
            page_count=inspection.page_count,
            relative_path=relative_path,
            validated_at=utc_now(),
        )
        receipt = self.sink.publish(validated, source_path)
        updated = self.journal.resolve_review_document(
            document=document,
            new_relative_path=relative_path,
            document_type=document_type,
            document_date=document_date,
            sync_status=receipt.sync_status.value,
        )
        if not updated:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONTENT_CONFLICT,
                "Review-Journaleintrag wurde zwischenzeitlich geändert",
            )
        try:
            if _sha256(source_path) == digest:
                source_path.unlink()
                review_copy_removed = True
            else:
                review_copy_removed = False
        except OSError:
            review_copy_removed = False
        return ReviewResolutionResult(
            document=document,
            resolved_path=receipt.target_path,
            sync_status=receipt.sync_status,
            review_copy_removed=review_copy_removed,
        )


def _review_connection(document: ReviewDocument) -> ProviderConnection:
    return ProviderConnection(
        connection_id=UUID(document.connection_id),
        provider_id=document.provider_id,
        tenant_id=TenantId(document.tenant_id),
        account_alias=document.account_alias,
        enabled=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
