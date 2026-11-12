"""UI-owned token boundary for Microsoft Graph mail access."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.security import assert_local_path


class GraphTokenProvider(Protocol):
    def get_access_token(self) -> str: ...


class CallbackGraphTokenProvider:
    """Adapt an interactive UI/MSAL service without embedding a console auth flow."""

    def __init__(self, acquire: Callable[[], str]) -> None:
        self._acquire = acquire

    def get_access_token(self) -> str:
        token = str(self._acquire() or "").strip()
        if not token:
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED, "Microsoft-Graph-Anmeldung erforderlich"
            )
        return token


class MsalInteractiveGraphTokenProvider:
    """Acquire Graph tokens through MSAL's visible system browser and DPAPI cache.

    ``app_factory`` and ``cache_factory`` are injectable for tests.  Production defaults
    deliberately fail closed when ``msal-extensions`` is not available instead of falling
    back to a plaintext JSON cache.
    """

    def __init__(
        self,
        *,
        client_id: str,
        authority: str,
        scopes: tuple[str, ...],
        cache_path: Path,
        app_factory: Callable[..., Any] | None = None,
        cache_factory: Callable[[Path], Any] | None = None,
    ) -> None:
        if not client_id.strip() or not authority.strip() or not scopes:
            raise ValueError("client_id, authority and scopes are required")
        assert_local_path(cache_path)
        self.client_id = client_id.strip()
        self.authority = authority.strip()
        self.scopes = tuple(scope.strip() for scope in scopes if scope.strip())
        self.cache_path = cache_path
        self._app_factory = app_factory
        self._cache_factory = cache_factory
        self._app: Any = None

    def get_access_token(self) -> str:
        app = self._application()
        for account in app.get_accounts() or ():
            result = app.acquire_token_silent(list(self.scopes), account=account)
            token = _token_from_result(result)
            if token:
                return token
        result = app.acquire_token_interactive(scopes=list(self.scopes))
        token = _token_from_result(result)
        if not token:
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED,
                "Microsoft-Graph-Anmeldung konnte nicht abgeschlossen werden",
            )
        return token

    def _application(self) -> Any:
        if self._app is not None:
            return self._app
        cache = (
            self._cache_factory(self.cache_path)
            if self._cache_factory
            else _dpapi_cache(self.cache_path)
        )
        factory = self._app_factory
        if factory is None:
            try:
                import msal  # type: ignore[import-untyped]
            except ImportError as exc:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.CONFIGURATION_ERROR,
                    "MSAL ist für Microsoft-Graph-Anmeldung nicht installiert",
                ) from exc
            factory = msal.PublicClientApplication
        self._app = factory(self.client_id, authority=self.authority, token_cache=cache)
        return self._app


def _token_from_result(result: Any) -> str:
    return str(result.get("access_token") or "").strip() if isinstance(result, dict) else ""


def _dpapi_cache(path: Path) -> Any:
    try:
        from msal_extensions import (  # type: ignore[import-untyped]
            FilePersistenceWithDataProtection,
            PersistedTokenCache,
        )
    except ImportError as exc:
        raise InvoiceCollectionError(
            InvoiceErrorCode.CONFIGURATION_ERROR,
            "msal-extensions für den geschützten Windows-Token-Cache fehlt",
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    return PersistedTokenCache(FilePersistenceWithDataProtection(str(path)))
