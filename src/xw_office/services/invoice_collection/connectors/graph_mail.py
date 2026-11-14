"""Generic Microsoft Graph attachment connector.

Authentication is deliberately injected.  The connector never starts a console-only auth
flow and never follows links found in messages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    DownloadedArtifact,
    ProviderConnection,
)
from xw_office.services.invoice_collection.ports import CancelToken


class GraphAttachmentReader(Protocol):
    def list_messages(self) -> Iterable[dict[str, Any]]: ...

    def download_attachment(
        self, message_id: str, attachment_id: str, destination: Path
    ) -> None: ...


@dataclass(frozen=True)
class MailMatchPolicy:
    sender_domains: frozenset[str] = frozenset()
    document_type: DocumentType = DocumentType.EXPENSE_INVOICE

    def accepts(self, message: dict[str, Any]) -> bool:
        if not self.sender_domains:
            return False
        domain = str(message.get("sender_domain") or "").strip().casefold()
        return domain in self.sender_domains


class GraphMailAttachmentConnector:
    """Discover and download actual PDF attachments from injected Graph access."""

    route_key = "mail_pdf"

    def __init__(
        self,
        *,
        connection: ProviderConnection,
        reader: GraphAttachmentReader,
        policy: MailMatchPolicy | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> None:
        self.connection = connection
        self.reader = reader
        self.policy = policy or MailMatchPolicy()
        self.start = start
        self.end = end

    def discover(self) -> list[DocumentCandidate]:
        candidates: list[DocumentCandidate] = []
        for message in self.reader.list_messages():
            if not self.policy.accepts(message) or not _in_period(message, self.start, self.end):
                continue
            message_id = str(message.get("id") or "").strip()
            if not message_id:
                continue
            for attachment in message.get("attachments") or ():
                if not isinstance(attachment, dict) or not _looks_like_pdf(attachment):
                    continue
                attachment_id = str(attachment.get("id") or "").strip()
                if not attachment_id:
                    continue
                candidates.append(
                    DocumentCandidate(
                        connection=self.connection,
                        route_key=self.route_key,
                        source_id=f"{message_id}:{attachment_id}",
                        external_id=f"{message_id}:{attachment_id}",
                        document_type=self.policy.document_type,
                        original_filename=str(attachment.get("name") or "attachment.pdf"),
                        # Receipt time is retrieval provenance, not an invoice date.
                        document_date=None,
                        metadata={
                            "message_id": message_id,
                            "attachment_id": attachment_id,
                            "received_at": str(message.get("received_at") or ""),
                        },
                    )
                )
        return candidates

    def download(
        self,
        candidate: DocumentCandidate,
        workspace: Path,
        cancel: CancelToken | None = None,
    ) -> DownloadedArtifact:
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Mailabruf abgebrochen")
        message_id = str(candidate.metadata.get("message_id") or "")
        attachment_id = str(candidate.metadata.get("attachment_id") or candidate.external_id or "")
        if not message_id or not attachment_id:
            raise ValueError("Mailkandidat enthält keine stabile Attachment-Identität")
        workspace.mkdir(parents=True, exist_ok=True)
        destination = workspace / candidate.original_filename
        self.reader.download_attachment(message_id, attachment_id, destination)
        return DownloadedArtifact(candidate=candidate, path=destination)

    def probe(self) -> None:
        probe = getattr(self.reader, "probe_mailbox", None)
        if not callable(probe):
            raise RuntimeError("Graph-Mailbox-Probe wird vom Reader nicht unterstützt")
        probe()

    def close(self) -> None:
        close = getattr(self.reader, "close", None)
        if callable(close):
            close()


def _looks_like_pdf(attachment: dict[str, Any]) -> bool:
    name = str(attachment.get("name") or "").casefold()
    content_type = str(attachment.get("content_type") or "").casefold()
    return content_type == "application/pdf" or name.endswith(".pdf")


def _in_period(message: dict[str, Any], start: date | None, end: date | None) -> bool:
    received = _parse_date(message.get("received_at"))
    if received is None:
        return True
    return (start is None or received >= start) and (end is None or received <= end)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
