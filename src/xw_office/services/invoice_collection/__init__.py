"""Secure, provider-independent invoice collection primitives."""

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    ProviderConnection,
    TenantId,
)

__all__ = ["DocumentCandidate", "DocumentType", "ProviderConnection", "TenantId"]
