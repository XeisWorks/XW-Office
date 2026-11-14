"""Typed errors that can safely cross the UI boundary."""
from __future__ import annotations

from enum import StrEnum


class InvoiceErrorCode(StrEnum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INVALID_DOCUMENT = "INVALID_DOCUMENT"
    DESTINATION_UNAVAILABLE = "DESTINATION_UNAVAILABLE"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"
    OUT_OF_PERIOD = "OUT_OF_PERIOD"
    UNSUPPORTED_ACCOUNT = "UNSUPPORTED_ACCOUNT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    PROVIDER_CHANGED = "PROVIDER_CHANGED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class InvoiceCollectionError(RuntimeError):
    """An actionable error with a stable, non-sensitive code."""

    def __init__(self, code: InvoiceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class DocumentValidationError(InvoiceCollectionError):
    """Raised when a downloaded artifact is not an acceptable PDF."""

    def __init__(self, message: str) -> None:
        super().__init__(InvoiceErrorCode.INVALID_DOCUMENT, message)


class DestinationError(InvoiceCollectionError):
    """Raised when a sink cannot safely publish a document."""

    def __init__(self, message: str) -> None:
        super().__init__(InvoiceErrorCode.DESTINATION_UNAVAILABLE, message)
