"""FinanzOnline / UVA SOAP integration (injectable backend for zeep or mocks)."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.uva_soap import (
    FinanzOnlineFileUploadBackend,
    UnconfiguredUvaSoapBackend,
    UvaSoapBackend,
    UvaSubmitResult,
    ZeepUvaSoapBackend,
)

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService

logger = logging.getLogger(__name__)


class FinanzOnlineClient:
    """SOAP entry point; credentials resolved via SecretService → config fallback."""

    def __init__(
        self,
        config: AppConfig,
        *,
        uva_backend: UvaSoapBackend | None = None,
        secret_service: "SecretService | None" = None,
    ) -> None:
        self._config = config
        self._secrets = secret_service
        self._uva_backend: UvaSoapBackend = uva_backend or self._build_default_backend()

    # ------------------------------------------------------------------
    # Credential helpers — SecretService > env > config > None
    # ------------------------------------------------------------------

    def participant_id(self) -> str | None:
        """FinanzOnline TeilnehmerId (FON_TEILNEHMER_ID)."""
        if self._secrets:
            val = self._secrets.get_secret("FON_TEILNEHMER_ID")
            if val:
                return val
        env_val = (os.getenv("FON_TEILNEHMER_ID", "") or "").strip()
        return env_val or None

    def user_id(self) -> str | None:
        """FinanzOnline BenutzerId (FON_BENUTZER_ID)."""
        if self._secrets:
            value = self._secrets.get_secret("FON_BENUTZER_ID")
            if value:
                return value
        env_val = (os.getenv("FON_BENUTZER_ID", "") or "").strip()
        return env_val or None

    def fon_pin(self) -> str | None:
        """FinanzOnline PIN (FON_PIN)."""
        if self._secrets:
            value = self._secrets.get_secret("FON_PIN")
            if value:
                return value
        env_val = (os.getenv("FON_PIN", "") or "").strip()
        return env_val or None

    def manufacturer_id(self) -> str | None:
        """FinanzOnline Hersteller-ID, typically the software UID."""
        if self._secrets:
            value = self._secrets.get_secret("FON_HERSTELLER_ID") or self._secrets.get_secret("FINANZONLINE_UID")
            if value:
                return value
        env_val = (
            os.getenv("FON_HERSTELLER_ID", "")
            or os.getenv("FINANZONLINE_UID", "")
            or self._config.finanzonline.hersteller_id
            or ""
        ).strip()
        return env_val or None

    def fastnr(self) -> str | None:
        """9-digit FinanzOnline tax number required by U30 XML."""
        if self._secrets:
            value = (
                self._secrets.get_secret("FINANZONLINE_FASTNR")
                or self._secrets.get_secret("FINANZONLINE_STEUERNUMMER")
                or self._secrets.get_secret("FON_STEUERNUMMER")
                or self._secrets.get_secret("FON_FASTNR")
            )
            if value:
                return value
        env_val = (
            os.getenv("FINANZONLINE_FASTNR", "")
            or os.getenv("FINANZONLINE_STEUERNUMMER", "")
            or os.getenv("FON_STEUERNUMMER", "")
            or os.getenv("FON_FASTNR", "")
            or self._config.finanzonline.fastnr
            or ""
        ).strip()
        return env_val or None

    def has_credentials(self) -> bool:
        """True when all three FON credentials are available."""
        return bool(self.participant_id() and self.user_id() and self.fon_pin())

    def has_submission_credentials(self) -> bool:
        """True when U30 login and XML identity fields are available."""
        return bool(self.has_credentials() and self.manufacturer_id() and self.fastnr())

    def backend_mode(self) -> str:
        """Human-readable backend mode for UI/status text."""
        if isinstance(self._uva_backend, FinanzOnlineFileUploadBackend):
            return "fileupload/test" if self._config.finanzonline.test_mode else "fileupload/produktiv"
        if isinstance(self._uva_backend, ZeepUvaSoapBackend):
            return "live/test" if self._config.finanzonline.test_mode else "live"
        return "mock/off"

    # ------------------------------------------------------------------

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Submit UVA payload via configured SOAP backend."""
        return self._uva_backend.submit_uva(payload)

    def submit_zm(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Submit ZM/U13 payload via configured FileUpload backend."""
        return self._uva_backend.submit_zm(payload)

    def _build_default_backend(self) -> UvaSoapBackend:
        wsdl = ((self._config.finanzonline.wsdl_url or "") or os.getenv("FON_SOAP_WSDL") or "").strip()
        operation = (
            (self._config.finanzonline.operation_name or "")
            or os.getenv("FON_SOAP_OPERATION")
            or "submitUva"
        ).strip() or "submitUva"
        participant_id = self.participant_id() or ""
        user_id = self.user_id() or ""
        pin = self.fon_pin() or ""
        manufacturer_id = self.manufacturer_id() or ""
        fastnr = self.fastnr() or ""

        if wsdl and participant_id and user_id and pin:
            static_kwargs = {
                "teilnehmer_id": participant_id,
                "benutzer_id": user_id,
                "pin": pin,
            }
            logger.info("FinanzOnlineClient: using Zeep live backend (%s)", operation)
            return ZeepUvaSoapBackend(
                wsdl_url=wsdl,
                operation_name=operation,
                static_kwargs=static_kwargs,
            )
        session_wsdl = (
            self._config.finanzonline.session_wsdl_url
            or os.getenv("FON_SESSION_WSDL")
            or "https://finanzonline.bmf.gv.at/fonws/ws/sessionService.wsdl"
        ).strip()
        upload_wsdl = (
            self._config.finanzonline.upload_wsdl_url
            or os.getenv("FON_UPLOAD_WSDL")
            or "https://finanzonline.bmf.gv.at/fon/ws/fileuploadService.wsdl"
        ).strip()
        if session_wsdl and upload_wsdl and participant_id and user_id and pin and manufacturer_id and fastnr:
            logger.info("FinanzOnlineClient: using FileUpload backend")
            return FinanzOnlineFileUploadBackend(
                session_wsdl_url=session_wsdl,
                upload_wsdl_url=upload_wsdl,
                tid=participant_id,
                benid=user_id,
                pin=pin,
                hersteller_id=manufacturer_id,
                fastnr=fastnr,
                test_mode=self._config.finanzonline.test_mode,
                u30_xsd_path=self._config.finanzonline.u30_xsd_path,
                u13_xsd_path=self._config.finanzonline.u13_xsd_path,
            )

        missing_parts: list[str] = []
        if not session_wsdl:
            missing_parts.append("FON_SESSION_WSDL / finanzonline.session_wsdl_url")
        if not upload_wsdl:
            missing_parts.append("FON_UPLOAD_WSDL / finanzonline.upload_wsdl_url")
        if not participant_id:
            missing_parts.append("FON_TEILNEHMER_ID")
        if not user_id:
            missing_parts.append("FON_BENUTZER_ID")
        if not pin:
            missing_parts.append("FON_PIN")
        if not manufacturer_id:
            missing_parts.append("FINANZONLINE_UID / FON_HERSTELLER_ID")
        if not fastnr:
            missing_parts.append("FINANZONLINE_FASTNR / FINANZONLINE_STEUERNUMMER / FON_STEUERNUMMER")
        reason = "FinanzOnline SOAP nicht konfiguriert. Fehlend: " + ", ".join(missing_parts)
        logger.info("FinanzOnlineClient: using unconfigured/mock backend (%s)", reason)
        return UnconfiguredUvaSoapBackend(reason=reason)
