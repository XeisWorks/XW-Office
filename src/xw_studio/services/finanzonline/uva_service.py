"""UVA / ZM submission orchestration (SOAP via zeep — implement per filing type)."""
from __future__ import annotations

import logging
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.client import FinanzOnlineClient
from xw_studio.services.finanzonline.monthly_snapshot import TaxMonthlySnapshotStore
from xw_studio.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_studio.services.finanzonline.uva_preview import UvaPreviewService
from xw_studio.services.finanzonline.uva_references import compare_uva_reference
from xw_studio.services.finanzonline.uva_soap import UvaSubmitResult
from xw_studio.services.finanzonline.zm_service import ZmService

logger = logging.getLogger(__name__)
_TAX_SNAPSHOT_SCHEMA_VERSION = "uva_zm_snapshot_v4"


class UvaService:
    """High-level UVA workflow; keeps SOAP details out of the UI."""

    def __init__(
        self,
        config: AppConfig,
        client: FinanzOnlineClient,
        preview_service: UvaPreviewService | None = None,
        payload_service: UvaPayloadService | None = None,
        zm_service: ZmService | None = None,
        snapshot_store: TaxMonthlySnapshotStore | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._preview_service = preview_service
        self._payload_service = payload_service
        self._zm_service = zm_service
        self._snapshot_store = snapshot_store
        self._calculation_cache: dict[tuple[int, int], dict[str, Any]] = {}

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
            f"ZM/U13: {'aktiv, Soll-Berechnung aus sevDesk-Rechnungen und Gutschriften' if self._zm_service else 'nicht aktiv'}\n"
            f"PostgreSQL: {'konfiguriert' if has_url else 'nicht konfiguriert (nur .env)'}\n"
            f"FinanzOnline-Login: {'vorhanden' if has_fon else 'fehlt (Einstellungen > Token/.env)'}\n"
            f"FinanzOnline-U30-Sendung: {'vollstaendig konfiguriert' if has_submission else 'FASTNR/Hersteller-ID pruefen'}"
        )

    def calculate_month(self, year: int, month: int, *, refresh: bool = False) -> dict[str, Any]:
        """Build the single cash-basis monthly UVA calculation for UI and submission."""
        cache_key = (year, month)
        if not refresh and cache_key in self._calculation_cache:
            cached = deepcopy(self._calculation_cache[cache_key])
            cache_meta = dict(cached.get("cache") or {})
            cache_meta.update({"hit": True, "source": "memory"})
            cached["cache"] = cache_meta
            return cached
        if not refresh and self._snapshot_store is not None:
            snapshot = self._snapshot_store.get_snapshot(year, month)
            if snapshot is not None and snapshot.payload.get("snapshot_schema_version") == _TAX_SNAPSHOT_SCHEMA_VERSION:
                payload = deepcopy(snapshot.payload)
                payload["cache"] = {
                    "hit": True,
                    "source": "persistent",
                    "snapshot_hash": snapshot.payload_hash,
                    "age_seconds": round(snapshot.age_seconds, 3),
                }
                self._calculation_cache[cache_key] = deepcopy(payload)
                return payload
        if self._preview_service is None or self._payload_service is None:
            return {
                "jahr": year,
                "monat": month,
                "status": "entwurf",
                "quelle": "xw_studio",
                "hinweis": "Keine IST-Berechnung konfiguriert.",
            }
        started = time.perf_counter()
        preview = self._preview_service.build_preview(year, month)
        calculated = self._payload_service.build_payload_from_preview(preview)
        payload: dict[str, Any] = {
            "jahr": year,
            "monat": month,
            "status": "entwurf",
            "quelle": "xw_studio",
            "berechnungsart": "IST",
            "snapshot_schema_version": _TAX_SNAPSHOT_SCHEMA_VERSION,
            "preview": preview.model_dump(),
            "preview_text": self._preview_service.render_preview_text(preview),
            "kennzahlen": calculated.kennzahlen.model_dump(),
            "zahlbetrag": calculated.zahlbetrag,
            "rule_version": calculated.rule_version,
            "warnings": list(calculated.warnings),
            "kennzahlen_text": self._payload_service.render_kennzahlen_text(calculated),
        }
        if self._zm_service is not None:
            zm = self._zm_service.calculate_month(year, month)
            payload["zm"] = zm.model_dump()
            payload["zm_text"] = self._zm_service.render_preview_text(zm)
        payload["reference_comparison"] = compare_uva_reference(
            year=year,
            month=month,
            kennzahlen=payload["kennzahlen"],
            zahlbetrag=payload["zahlbetrag"],
        )
        payload["reconciliation"] = build_uva_zm_reconciliation(payload)
        payload["data_quality"] = build_data_quality(payload)
        snapshot_hash = None
        if self._snapshot_store is not None:
            snapshot = self._snapshot_store.put_snapshot(year, month, payload)
            if snapshot is not None:
                snapshot_hash = snapshot.payload_hash
        payload["cache"] = {
            "hit": False,
            "source": "live",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "snapshot_hash": snapshot_hash,
        }
        self._calculation_cache[cache_key] = deepcopy(payload)
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
        cached = self._calculation_cache.get((year, month))
        if cached and isinstance(cached.get("kennzahlen"), dict):
            kennzahlen = dict(cached["kennzahlen"])
            zahlbetrag = str(cached.get("zahlbetrag") or "0.00")
            warnings = list(cached.get("warnings") or [])
            rule_version = str(cached.get("rule_version") or "U30_01_2022")
            data_quality = dict(cached.get("data_quality") or {})
            cache_meta = dict(cached.get("cache") or {})
        else:
            calculated = self._payload_service.build_payload(year, month)
            kennzahlen = calculated.kennzahlen.model_dump()
            zahlbetrag = calculated.zahlbetrag
            warnings = list(calculated.warnings)
            rule_version = calculated.rule_version
            data_quality = {}
            cache_meta = {}
        submission_kennzahlen = {
            "KZ000": kennzahlen.get("A000", "0.00"),
            "KZ011": kennzahlen.get("A011", "0.00"),
            "KZ017": kennzahlen.get("A017", "0.00"),
            "KZ021": kennzahlen.get("A021", "0.00"),
            "KZ022": kennzahlen.get("A022", "0.00"),
            "KZ029": kennzahlen.get("A029", "0.00"),
            "KZ006": kennzahlen.get("A006", "0.00"),
            "KZ057": kennzahlen.get("A057", "0.00"),
            "KZ070": kennzahlen.get("B070", "0.00"),
            "KZ072": kennzahlen.get("B072", "0.00"),
            "KZ060": kennzahlen.get("C060", "0.00"),
            "KZ065": kennzahlen.get("C065", "0.00"),
            "KZ066": kennzahlen.get("C066", "0.00"),
            "KZ090": kennzahlen.get("D090", "0.00"),
        }
        return {
            "meldung": "U30",
            "jahr": year,
            "monat": month,
            "zeitraum": f"{year:04d}-{month:02d}",
            "quelle": "xw_studio",
            "rule_version": rule_version,
            "kennzahlen": submission_kennzahlen,
            "zahlbetrag": zahlbetrag,
            "warnings": warnings,
            "data_quality": data_quality,
            "snapshot_hash": cache_meta.get("snapshot_hash"),
        }

    def submit_month(self, year: int, month: int) -> UvaSubmitResult:
        """Calculate and submit one monthly U30 payload, then U13/ZM when configured."""
        monthly_payload = self.calculate_month(year, month)
        data_quality = monthly_payload.get("data_quality")
        if isinstance(data_quality, dict) and int(data_quality.get("blocking_count") or 0) > 0:
            blocking = data_quality.get("blocking")
            details = "; ".join(str(item) for item in blocking) if isinstance(blocking, list) else ""
            return UvaSubmitResult(
                ok=False,
                message=f"UVA nicht gesendet: Datenqualitaet blockiert. {details}".strip(),
                uva_payload=monthly_payload,
            )
        uva_payload = self.build_submission_payload(year, month)
        result = self.submit_uva(uva_payload)
        result.uva_payload = uva_payload
        if not result.ok or self._zm_service is None:
            return result

        cached = self._calculation_cache.get((year, month))
        cached_zm = cached.get("zm") if isinstance(cached, dict) else None
        if isinstance(cached_zm, dict):
            zm_rows = list(cached_zm.get("rows") or [])
            zm_invalid = list(cached_zm.get("invalid") or [])
            zm_warnings = list(cached_zm.get("warnings") or [])
        else:
            zm = self._zm_service.calculate_month(year, month)
            zm_rows = [row.model_dump() for row in zm.rows]
            zm_invalid = list(zm.invalid)
            zm_warnings = list(zm.warnings)

        result.zm_rows = len(zm_rows)
        if zm_invalid:
            result.zm_ok = False
            result.zm_message = "ZM nicht gesendet: " + "; ".join(str(item) for item in zm_invalid)
            return result
        if not zm_rows:
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
            "rows": zm_rows,
            "warnings": zm_warnings,
        }
        result.zm_payload = zm_payload
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


def build_uva_zm_reconciliation(payload: dict[str, Any]) -> dict[str, Any]:
    kennzahlen = payload.get("kennzahlen")
    zm = payload.get("zm")
    kz = kennzahlen if isinstance(kennzahlen, dict) else {}
    zm_rows = zm.get("rows") if isinstance(zm, dict) else []
    rows = [row for row in zm_rows if isinstance(row, dict)] if isinstance(zm_rows, list) else []

    zm_delivery = sum(Decimal(int(row.get("amount_eur_int") or 0)) for row in rows if row.get("kind") == "delivery")
    zm_service = sum(Decimal(int(row.get("amount_eur_int") or 0)) for row in rows if row.get("kind") == "service")
    zm_dreieck = sum(Decimal(int(row.get("amount_eur_int") or 0)) for row in rows if row.get("kind") == "dreieck")
    a017 = _decimal(kz.get("A017"))
    a021 = _decimal(kz.get("A021"))

    notes = [
        "UVA ist IST nach Zahlungs-/Beleglogik; ZM/U13 ist Soll nach Rechnungsdatum.",
        "ZM-Betraege sind nach UID/Art auf ganze Euro gerundet; UVA-Kennzahlen bleiben centgenau.",
    ]
    delivery_delta = (a017 - zm_delivery).quantize(Decimal("0.01"))
    service_delta = (a021 - zm_service).quantize(Decimal("0.01"))
    if delivery_delta != Decimal("0.00"):
        notes.append(f"A017 minus ZM-Lieferungen: {delivery_delta:.2f} EUR.")
    if service_delta != Decimal("0.00"):
        notes.append(f"A021 minus ZM-SOLEI: {service_delta:.2f} EUR.")

    return {
        "period": f"{int(payload.get('jahr') or 0):04d}-{int(payload.get('monat') or 0):02d}",
        "uva_a017": f"{a017:.2f}",
        "uva_a021": f"{a021:.2f}",
        "zm_delivery_rounded": str(int(zm_delivery)),
        "zm_service_rounded": str(int(zm_service)),
        "zm_dreieck_rounded": str(int(zm_dreieck)),
        "delivery_delta": f"{delivery_delta:.2f}",
        "service_delta": f"{service_delta:.2f}",
        "notes": notes,
    }


def render_reconciliation_text(reconciliation: dict[str, Any]) -> str:
    if not reconciliation:
        return ""
    lines = [
        "Abstimmung UVA <-> ZM",
        f"Periode: {reconciliation.get('period') or '-'}",
        f"A017 innergemeinschaftliche Lieferungen: EUR {reconciliation.get('uva_a017') or '0.00'}",
        f"ZM Lieferungen gerundet: EUR {reconciliation.get('zm_delivery_rounded') or '0'}",
        f"Delta Lieferung: EUR {reconciliation.get('delivery_delta') or '0.00'}",
        f"A021 sonstige Leistungen/RC: EUR {reconciliation.get('uva_a021') or '0.00'}",
        f"ZM SOLEI gerundet: EUR {reconciliation.get('zm_service_rounded') or '0'}",
        f"Delta SOLEI: EUR {reconciliation.get('service_delta') or '0.00'}",
    ]
    notes = reconciliation.get("notes")
    if isinstance(notes, list) and notes:
        lines.extend(["", "Hinweise:"])
        lines.extend(f"- {note}" for note in notes if str(note).strip())
    return "\n".join(lines)


def build_data_quality(payload: dict[str, Any]) -> dict[str, Any]:
    warnings = payload.get("warnings")
    warning_items = [str(item) for item in warnings if isinstance(item, str)] if isinstance(warnings, list) else []
    reference_comparison = payload.get("reference_comparison")
    zm = payload.get("zm")
    zm_invalid = zm.get("invalid") if isinstance(zm, dict) else []
    invalid_items = [str(item) for item in zm_invalid if str(item).strip()] if isinstance(zm_invalid, list) else []
    blocking = list(invalid_items)
    if isinstance(reference_comparison, dict) and reference_comparison.get("within_tolerance") is False:
        amount = reference_comparison.get("zahlbetrag")
        if isinstance(amount, dict):
            blocking.append(
                "Golden-Master-Abweichung ausserhalb Toleranz: "
                f"Live {amount.get('actual')} / Soll {amount.get('expected')} / Delta {amount.get('delta')}"
            )
        else:
            blocking.append("Golden-Master-Abweichung ausserhalb Toleranz")
    status = "abgabebereit"
    if blocking:
        status = "blockiert"
    elif warning_items:
        status = "pruefen"
    return {
        "status": status,
        "blocking_count": len(blocking),
        "warning_count": len(warning_items),
        "blocking": blocking,
        "warnings": warning_items,
        "rule_version": str(payload.get("rule_version") or "U30_01_2022"),
        "reference_within_tolerance": (
            reference_comparison.get("within_tolerance")
            if isinstance(reference_comparison, dict)
            else None
        ),
    }


def render_data_quality_text(data_quality: dict[str, Any]) -> str:
    if not data_quality:
        return ""
    lines = [
        "Datenqualitaet",
        f"Status: {data_quality.get('status') or 'unbekannt'}",
        f"Regelversion: {data_quality.get('rule_version') or '-'}",
        f"Blockierend: {data_quality.get('blocking_count') or 0}",
        f"Hinweise: {data_quality.get('warning_count') or 0}",
    ]
    blocking = data_quality.get("blocking")
    if isinstance(blocking, list) and blocking:
        lines.extend(["", "Blockierende Punkte:"])
        lines.extend(f"- {item}" for item in blocking if str(item).strip())
    return "\n".join(lines)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
