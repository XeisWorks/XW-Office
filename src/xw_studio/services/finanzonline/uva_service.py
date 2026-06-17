"""UVA / ZM submission orchestration (SOAP via zeep — implement per filing type)."""
from __future__ import annotations

import logging
from typing import Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.client import FinanzOnlineClient
from xw_studio.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_studio.services.finanzonline.uva_preview import UvaPreviewService
from xw_studio.services.finanzonline.uva_soap import UvaSubmitResult
from xw_studio.services.finanzonline.zm_service import ZmService

logger = logging.getLogger(__name__)


class UvaService:
    """High-level UVA workflow; keeps SOAP details out of the UI."""

    def __init__(
        self,
        config: AppConfig,
        client: FinanzOnlineClient,
        preview_service: UvaPreviewService | None = None,
        payload_service: UvaPayloadService | None = None,
        zm_service: ZmService | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._preview_service = preview_service
        self._payload_service = payload_service
        self._zm_service = zm_service

    def describe_capabilities(self) -> str:
        """Human-readable status for the Steuern > UVA tab."""
        has_url = bool(self._config.database_url)
        has_fon = self._client.has_credentials()
        has_submission = self._client.has_submission_credentials()
        mode = self._client.backend_mode()
        calculation_mode = (
            "aktiv"
            if self._preview_service is not None and self._payload_service is not None
            else "nicht aktiv"
        )
        return (
            "UVA-Modul: eine IST-Monatsberechnung aus sevDesk-Zahlungsdaten; "
            "FinanzOnline nutzt dieselben Kennzahlen.\n"
            f"Backend-Modus: {mode}\n"
            f"IST-Berechnung: {calculation_mode}\n"
            "sevDesk-Aggregator: nicht als Berechnungsquelle verwendet\n"
            f"ZM/U13: {'aktiv, Soll-Berechnung aus sevDesk-Rechnungen' if self._zm_service else 'nicht aktiv'}\n"
            f"PostgreSQL: {'konfiguriert' if has_url else 'nicht konfiguriert (nur .env)'}\n"
            f"FinanzOnline-Login: {'vorhanden' if has_fon else 'fehlt (Einstellungen > Token/.env)'}\n"
            f"FinanzOnline-U30-Sendung: {'vollstaendig konfiguriert' if has_submission else 'FASTNR/Hersteller-ID pruefen'}"
        )

    def calculate_month(self, year: int, month: int) -> dict[str, Any]:
        """Build the single cash-basis monthly UVA calculation for UI and submission."""
        if self._preview_service is None or self._payload_service is None:
            return {
                "jahr": year,
                "monat": month,
                "status": "entwurf",
                "quelle": "xw_studio",
                "hinweis": "Keine IST-Berechnung konfiguriert.",
            }
        preview = self._preview_service.build_preview(year, month)
        calculated = self._payload_service.build_payload_from_preview(preview)
        payload: dict[str, Any] = {
            "jahr": year,
            "monat": month,
            "status": "entwurf",
            "quelle": "xw_studio",
            "berechnungsart": "IST",
            "preview": preview.model_dump(),
            "preview_text": self._preview_service.render_preview_text(preview),
            "kennzahlen": calculated.kennzahlen.model_dump(),
            "zahlbetrag": calculated.zahlbetrag,
            "warnings": list(calculated.warnings),
            "kennzahlen_text": self._payload_service.render_kennzahlen_text(calculated),
        }
        if self._zm_service is not None:
            zm = self._zm_service.calculate_month(year, month)
            payload["zm"] = zm.model_dump()
            payload["zm_text"] = self._zm_service.render_preview_text(zm)
        return payload

    def build_preview(self, year: int, month: int) -> dict[str, Any]:
        """Backward-compatible alias for tests and older UI code."""
        return self.calculate_month(year, month)

    def mock_build_payload(self, year: int, month: int) -> dict[str, Any]:
        """Backward-compatible alias for UI/tests; no mock calculation is used."""
        try:
            return self.calculate_month(year, month)
        except Exception as exc:
            logger.exception("UVA calculation failed for %s-%s", year, month)
            return {
                "jahr": year,
                "monat": month,
                "status": "fehler",
                "quelle": "xw_studio",
                "fehler": str(exc),
            }

    def build_submission_payload(self, year: int, month: int) -> dict[str, Any]:
        """Build the U30 submission payload from the calculated kennzahlen."""
        if self._payload_service is None:
            raise RuntimeError("Keine Kennzahlen-Berechnung für UVA konfiguriert.")
        calculated = self._payload_service.build_payload(year, month)
        kz = calculated.kennzahlen
        submission_kennzahlen = {
            "KZ000": kz.A000,
            "KZ011": kz.A011,
            "KZ017": kz.A017,
            "KZ021": kz.A021,
            "KZ022": kz.A022,
            "KZ029": kz.A029,
            "KZ006": kz.A006,
            "KZ057": kz.A057,
            "KZ070": kz.B070,
            "KZ072": kz.B072,
            "KZ060": kz.C060,
            "KZ065": kz.C065,
            "KZ066": kz.C066,
            "KZ090": kz.D090,
        }
        return {
            "meldung": "U30",
            "jahr": year,
            "monat": month,
            "zeitraum": f"{year:04d}-{month:02d}",
            "quelle": "xw_studio",
            "kennzahlen": submission_kennzahlen,
            "zahlbetrag": calculated.zahlbetrag,
            "warnings": list(calculated.warnings),
        }

    def submit_month(self, year: int, month: int) -> UvaSubmitResult:
        """Calculate and submit one monthly U30 payload, then U13/ZM when configured."""
        result = self.submit_uva(self.build_submission_payload(year, month))
        if not result.ok or self._zm_service is None:
            return result

        zm = self._zm_service.calculate_month(year, month)
        result.zm_rows = len(zm.rows)
        if zm.invalid:
            result.zm_ok = False
            result.zm_message = "ZM nicht gesendet: " + "; ".join(zm.invalid)
            return result
        if not zm.rows:
            result.zm_ok = True
            result.zm_message = "Keine ZM-relevanten Rechnungen fuer diesen Monat."
            return result

        zm_payload = {
            "meldung": "U13",
            "jahr": year,
            "monat": month,
            "zeitraum": f"{year:04d}-{month:02d}",
            "quelle": "xw_studio",
            "berechnungsart": "SOLL",
            "kundeninfo": f"XW-Studio ZM {year:04d}-{month:02d}",
            "rows": [row.model_dump() for row in zm.rows],
            "warnings": list(zm.warnings),
        }
        zm_result = self._client.submit_zm(zm_payload)
        result.zm_ok = zm_result.ok
        result.zm_reference_id = zm_result.reference_id
        result.zm_message = zm_result.message
        result.zm_xml_validated = zm_result.xml_validated
        result.zm_xml_payload = zm_result.xml_payload
        return result

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Delegate to FinanzOnline SOAP/FileUpload client."""
        return self._client.submit_uva(payload)
