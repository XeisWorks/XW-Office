"""UVA SOAP submission contract and FinanzOnline backends."""
from __future__ import annotations

import logging
from typing import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from xw_studio.services.finanzonline.u30_xml import build_u30_xml, validate_u30_xml

logger = logging.getLogger(__name__)


class UvaSoapUnavailableError(RuntimeError):
    """Raised when no FinanzOnline/zeep backend is configured."""


class UvaSubmitResult(BaseModel):
    """Outcome of an (mock or real) UVA SOAP round-trip."""

    ok: bool
    reference_id: str | None = None
    message: str = Field(default="")
    test_mode: bool = True
    xml_validated: bool = False
    xml_payload: str = ""


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


class FinanzOnlineFileUploadBackend:
    """Production U30 backend: session login, file upload, logout."""

    def __init__(
        self,
        *,
        session_wsdl_url: str,
        upload_wsdl_url: str,
        tid: str,
        benid: str,
        pin: str,
        hersteller_id: str,
        fastnr: str,
        test_mode: bool = True,
        u30_xsd_path: str = "",
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._session_wsdl_url = session_wsdl_url.strip()
        self._upload_wsdl_url = upload_wsdl_url.strip()
        self._tid = tid.strip()
        self._benid = benid.strip()
        self._pin = pin.strip()
        self._hersteller_id = hersteller_id.strip()
        self._fastnr = fastnr.strip()
        self._test_mode = test_mode
        self._u30_xsd_path = u30_xsd_path.strip()
        if client_factory is None:
            from zeep import Client as ZeepClient

            self._client_factory: Callable[[str], Any] = ZeepClient
        else:
            self._client_factory = client_factory
        self.calls: list[dict[str, Any]] = []

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        self.calls.append(dict(payload))
        self._ensure_configured()
        xml_payload = build_u30_xml(payload, fastnr=self._fastnr)
        validate_u30_xml(xml_payload, self._u30_xsd_path or None)

        session_id = ""
        upload_message = ""
        try:
            session_client = self._client_factory(self._session_wsdl_url)
            login_raw = _call_soap_operation(
                session_client.service.login,
                tid=self._tid,
                benid=self._benid,
                pin=self._pin,
                herstellerid=self._hersteller_id,
            )
            login = _soap_response(login_raw)
            if login["rc"] != 0:
                return UvaSubmitResult(
                    ok=False,
                    reference_id=None,
                    message=f"FinanzOnline Login fehlgeschlagen: rc={login['rc']} {login['msg']}",
                    test_mode=self._test_mode,
                    xml_validated=True,
                    xml_payload=xml_payload,
                )
            session_id = login["id"]
            if not session_id:
                return UvaSubmitResult(
                    ok=False,
                    reference_id=None,
                    message="FinanzOnline Login lieferte keine Session-ID.",
                    test_mode=self._test_mode,
                    xml_validated=True,
                    xml_payload=xml_payload,
                )

            upload_client = self._client_factory(self._upload_wsdl_url)
            upload_raw = _call_soap_operation(
                upload_client.service.upload,
                tid=self._tid,
                benid=self._benid,
                id=session_id,
                art="U30",
                uebermittlung="T" if self._test_mode else "P",
                data=xml_payload,
            )
            upload = _soap_response(upload_raw)
            upload_message = f"rc={upload['rc']} {upload['msg']}".strip()
            return UvaSubmitResult(
                ok=upload["rc"] == 0,
                reference_id=session_id,
                message=upload_message,
                test_mode=self._test_mode,
                xml_validated=True,
                xml_payload=xml_payload,
            )
        except Exception as exc:
            logger.exception("FinanzOnline U30 FileUpload failed")
            return UvaSubmitResult(
                ok=False,
                reference_id=session_id or None,
                message=f"FinanzOnline U30 FileUpload fehlgeschlagen: {exc}",
                test_mode=self._test_mode,
                xml_validated=True,
                xml_payload=xml_payload,
            )
        finally:
            if session_id:
                try:
                    session_client = self._client_factory(self._session_wsdl_url)
                    _call_soap_operation(
                        session_client.service.logout,
                        tid=self._tid,
                        benid=self._benid,
                        id=session_id,
                    )
                except Exception:
                    logger.exception("FinanzOnline logout failed after upload: %s", upload_message)

    def _ensure_configured(self) -> None:
        missing: list[str] = []
        if not self._session_wsdl_url:
            missing.append("FON_SESSION_WSDL")
        if not self._upload_wsdl_url:
            missing.append("FON_UPLOAD_WSDL")
        if not self._tid:
            missing.append("FON_TEILNEHMER_ID")
        if not self._benid:
            missing.append("FON_BENUTZER_ID")
        if not self._pin:
            missing.append("FON_PIN")
        if not self._hersteller_id:
            missing.append("FINANZONLINE_UID / FON_HERSTELLER_ID")
        if not self._fastnr:
            missing.append("FINANZONLINE_FASTNR / FINANZONLINE_STEUERNUMMER")
        if missing:
            raise UvaSoapUnavailableError("FinanzOnline U30 nicht konfiguriert. Fehlend: " + ", ".join(missing))


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


def _call_soap_operation(operation: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        return operation(**kwargs)
    except TypeError:
        return operation(kwargs)


def _soap_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "id": str(raw.get("id") or ""),
            "rc": int(raw.get("rc") or 0),
            "msg": str(raw.get("msg") or raw.get("message") or ""),
        }
    return {
        "id": str(getattr(raw, "id", "") or ""),
        "rc": int(getattr(raw, "rc", 0) or 0),
        "msg": str(getattr(raw, "msg", "") or getattr(raw, "message", "") or ""),
    }
