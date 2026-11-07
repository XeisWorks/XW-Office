"""UI-owned token boundary for Microsoft Graph mail access."""
from __future__ import annotations

from typing import Callable, Protocol

from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)


class GraphTokenProvider(Protocol):
    def get_access_token(self) -> str: ...


class CallbackGraphTokenProvider:
    """Adapt an interactive UI/MSAL service without embedding a console auth flow."""

    def __init__(self, acquire: Callable[[], str]) -> None:
        self._acquire = acquire

    def get_access_token(self) -> str:
        token = str(self._acquire() or "").strip()
        if not token:
            raise InvoiceCollectionError(InvoiceErrorCode.AUTH_REQUIRED, "Microsoft-Graph-Anmeldung erforderlich")
        return token
