"""Immutable domain values shared by invoice connectors and sinks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4


class TenantId(StrEnum):
    XW = "xw"
    WUEDARA = "wuedara"


class DocumentType(StrEnum):
    FEE_INVOICE = "fee_invoice"
    EXPENSE_INVOICE = "expense_invoice"
    RECEIPT = "receipt"
    CREDIT_NOTE = "credit_note"
    PAYOUT_STATEMENT = "payout_statement"
    INCOME_STATEMENT = "income_statement"
    UNKNOWN = "unknown"


class DocumentOutcome(StrEnum):
    NEW = "NEW"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


class SyncStatus(StrEnum):
    LOCAL_SAVED = "LOCAL_SAVED"
    SYNC_PENDING = "SYNC_PENDING"
    CLOUD_VERIFIED = "CLOUD_VERIFIED"
    SYNC_FAILED = "SYNC_FAILED"


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("date range end must not precede start")


@dataclass(frozen=True)
class RouteSettings:
    route_key: str
    enabled: bool = True
    priority: int = 100
    options: Mapping[str, str] = field(default_factory=dict)
    secret_ref: str | None = None


@dataclass(frozen=True)
class ProviderConnection:
    connection_id: UUID
    provider_id: str
    tenant_id: TenantId
    account_alias: str
    enabled: bool = True
    route_settings: tuple[RouteSettings, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        provider_id: str,
        tenant_id: TenantId,
        account_alias: str,
        route_settings: tuple[RouteSettings, ...] = (),
    ) -> "ProviderConnection":
        return cls(
            connection_id=uuid4(),
            provider_id=provider_id,
            tenant_id=tenant_id,
            account_alias=account_alias,
            route_settings=route_settings,
        )


@dataclass(frozen=True)
class DocumentCandidate:
    connection: ProviderConnection
    route_key: str
    source_id: str
    external_id: str | None
    document_type: DocumentType
    original_filename: str
    document_date: date | None = None
    service_period: DateRange | None = None
    amount_minor: int | None = None
    currency: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadedArtifact:
    candidate: DocumentCandidate
    path: Path
    content_type: str | None = None


@dataclass(frozen=True)
class ValidatedDocument:
    candidate: DocumentCandidate
    sha256: str
    size_bytes: int
    page_count: int
    relative_path: Path
    validated_at: datetime


@dataclass(frozen=True)
class SinkReceipt:
    outcome: DocumentOutcome
    sync_status: SyncStatus
    target_path: Path
    sha256: str


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for journal and provenance records."""
    return datetime.now(timezone.utc)
