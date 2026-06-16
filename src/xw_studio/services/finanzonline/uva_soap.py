"""UVA SOAP submission contract and injectable backends (zeep to be wired later)."""
from __future__ import annotations

import logging
from typing import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UvaSoapUnavailableError(RuntimeError):
    """Raised when no FinanzOnline/zeep backend is configured."""


class UvaSubmitResult(BaseModel):
    """Outcome of an (mock or real) UVA SOAP round-trip."""

    ok: bool
    reference_id: str | None = None
    message: str = Field(default="")


class UvaSoapBackend(Protocol):
    """Pluggable SOAP layer — production uses zeep; tests use :class:`MockUvaSoapBackend`."""

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        ...


class UnconfiguredUvaSoapBackend:
    """Default backend until zeep endpoints and credentials are wired."""

    def __init__(self, *, reason: str | None = None) -> None:
        self._reason = reason or "FinanzOnline SOAP client is not configured (zeep backend missing)."

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        logger.warning("FinanzOnline UVA submission not configured; payload keys: %s", tuple(payload))
        raise UvaSoapUnavailableError(self._reason)


class MockUvaSoapBackend:
    """Test double simulating a successful FinanzOnline response (no network)."""

    def __init__(
        self,
        *,
        result: UvaSubmitResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result or UvaSubmitResult(
            ok=True,
            reference_id="MOCK-REF-001",
            message="accepted (mock)",
        )
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        self.calls.append(dict(payload))
        if self._error is not None:
            raise self._error
        return self._result.model_copy()


class ZeepUvaSoapBackend:
    """Live SOAP backend using zeep client and configurable operation name."""

    def __init__(
        self,
        *,
        wsdl_url: str,
        operation_name: str = "submitUva",
        static_kwargs: dict[str, Any] | None = None,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._wsdl_url = wsdl_url
        self._operation_name = operation_name
        self._static_kwargs = static_kwargs or {}
        if client_factory is None:
            from zeep import Client as ZeepClient  # local import for optional dependency behavior

            self._client_factory: Callable[[str], Any] = ZeepClient
        else:
            self._client_factory = client_factory
        self.calls: list[dict[str, Any]] = []

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        self.calls.append(dict(payload))
        if not self._wsdl_url.strip():
            raise UvaSoapUnavailableError("FON_SOAP_WSDL fehlt fuer Live-UVA.")

        try:
            client = self._client_factory(self._wsdl_url)
        except Exception as exc:
            logger.exception("FinanzOnline SOAP client init failed")
            return UvaSubmitResult(ok=False, reference_id=None, message=f"FinanzOnline SOAP init fehlgeschlagen: {exc}")

        op = getattr(client.service, self._operation_name, None)
        if op is None:
            raise UvaSoapUnavailableError(
                f"SOAP-Operation '{self._operation_name}' nicht gefunden.",
            )

        try:
            try:
                raw = op(payload=payload, **self._static_kwargs)
            except TypeError:
                try:
                    raw = op(**payload, **self._static_kwargs)
                except TypeError:
                    try:
                        raw = op(payload, **self._static_kwargs)
                    except TypeError:
                        raw = op(payload)
        except Exception as exc:
            logger.exception("FinanzOnline SOAP call failed")
            return UvaSubmitResult(ok=False, reference_id=None, message=f"FinanzOnline SOAP call failed: {exc}")

        if isinstance(raw, UvaSubmitResult):
            return raw
        if isinstance(raw, dict):
            ok = bool(raw.get("ok", True))
            ref = raw.get("reference_id") or raw.get("reference")
            msg = str(raw.get("message") or raw.get("msg") or "accepted")
            return UvaSubmitResult(ok=ok, reference_id=None if ref is None else str(ref), message=msg)
        if isinstance(raw, str):
            return UvaSubmitResult(ok=True, reference_id=None, message=raw)

        ok = bool(getattr(raw, "ok", True))
        raw_ref = getattr(raw, "reference_id", None) or getattr(raw, "reference", None)
        raw_msg = getattr(raw, "message", None) or getattr(raw, "msg", None)
        if raw_ref is not None or raw_msg is not None:
            return UvaSubmitResult(
                ok=ok,
                reference_id=None if raw_ref is None else str(raw_ref),
                message=str(raw_msg or "accepted"),
            )
        return UvaSubmitResult(ok=True, reference_id=None, message="accepted")
