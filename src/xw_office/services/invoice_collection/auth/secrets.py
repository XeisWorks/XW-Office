"""SecretRef-backed OS keyring boundary."""
from __future__ import annotations

from importlib import import_module
from typing import Protocol, cast

from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)


class SecretStore(Protocol):
    def get(self, secret_ref: str) -> str: ...

    def set(self, secret_ref: str, value: str) -> None: ...


class _KeyringModule(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...


class KeyringSecretStore:
    """Use the operating-system keyring; never fall back to a plaintext file."""

    service_name = "xw-office/invoice-collection"

    def __init__(self, *, keyring_module: _KeyringModule | None = None) -> None:
        if keyring_module is None:
            try:
                keyring_module = cast(_KeyringModule, import_module("keyring"))
            except ImportError as exc:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.CONFIGURATION_ERROR,
                    "keyring ist für Portal-Secrets nicht installiert",
                ) from exc
        self._keyring: _KeyringModule = keyring_module

    def get(self, secret_ref: str) -> str:
        ref = _validate_ref(secret_ref)
        value = self._keyring.get_password(self.service_name, ref)
        if not value:
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED, "Portal-Secret ist nicht hinterlegt"
            )
        return str(value)

    def set(self, secret_ref: str, value: str) -> None:
        ref = _validate_ref(secret_ref)
        if not str(value or "").strip():
            raise ValueError("secret value must not be empty")
        self._keyring.set_password(self.service_name, ref, str(value))


def _validate_ref(value: str) -> str:
    ref = str(value or "").strip()
    if not ref or "\n" in ref or "\r" in ref or len(ref) > 200:
        raise ValueError("invalid secret reference")
    return ref
