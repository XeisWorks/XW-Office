"""Zusammenfassende Meldung (ZM/U13) calculation from sevDesk invoices."""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from stdnum.eu import vat

from xw_office.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)

_DECIMAL_2 = Decimal("0.01")
ZmKind = Literal["delivery", "service", "dreieck"]


class ZmRow(BaseModel):
    uid: str
    amount_eur_int: int
    kind: ZmKind = "delivery"
    invoice_numbers: list[str] = Field(default_factory=list)
    customer: str = ""


class ZmCalculationResult(BaseModel):
    year: int
    month: int
    rows: list[ZmRow] = Field(default_factory=list)
    invalid: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    considered: int = 0
    selected: int = 0
    total_eur_int: int = 0

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.invalid)


class ZmInvoiceProvider(Protocol):
    def load_invoices(self, year: int, month: int) -> list[dict[str, Any]]:
        ...

    def load_credit_notes(self, year: int, month: int) -> list[dict[str, Any]]:
        ...

    def load_positions(self, resource: str, document_id: str) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class _Bucket:
    amount: Decimal
    invoices: list[str]
    customer: str


class SevdeskZmInvoiceProvider:
    """Read ZM-relevant source invoices by invoice date (Soll-Versteuerung)."""

    def __init__(self, connection: SevdeskConnection, *, page_size: int = 200, max_pages: int = 100) -> None:
        self._connection = connection
        self._page_size = page_size
        self._max_pages = max_pages
        self._contact_cache: dict[str, dict[str, Any]] = {}
        self._position_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def load_invoices(self, year: int, month: int) -> list[dict[str, Any]]:
        return self._load_dated_resource(
            "/Invoice",
            year,
            month,
            date_from_key="invoiceDate_from",
            date_to_key="invoiceDate_to",
            timestamp_start_key="startDate",
            timestamp_end_key="endDate",
        )

    def load_credit_notes(self, year: int, month: int) -> list[dict[str, Any]]:
        return self._load_dated_resource(
            "/CreditNote",
            year,
            month,
            date_from_key="creditNoteDate_from",
            date_to_key="creditNoteDate_to",
            timestamp_start_key="startDate",
            timestamp_end_key="endDate",
        )

    def _load_dated_resource(
        self,
        path: str,
        year: int,
        month: int,
        *,
        date_from_key: str,
        date_to_key: str,
        timestamp_start_key: str,
        timestamp_end_key: str,
    ) -> list[dict[str, Any]]:
        start, end = _month_bounds(year, month)
        start_ts, end_ts = _month_timestamp_bounds(year, month)
        documents: list[dict[str, Any]] = []
        offset = 0
        page = 0
        while page < self._max_pages:
            params = {
                "embed": "contact",
                "limit": self._page_size,
                "offset": offset,
                date_from_key: start,
                date_to_key: end,
                timestamp_start_key: start_ts,
                timestamp_end_key: end_ts,
                "showAll": "true",
            }
            response = self._connection.get(path, params=params)
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else None
            batch = [item for item in objects if isinstance(item, dict)] if isinstance(objects, list) else []
            if not batch:
                break
            documents.extend(self._with_contact_fallback(item) for item in batch)
            if len(batch) < self._page_size:
                break
            offset += self._page_size
            page += 1
        return documents

    def _with_contact_fallback(self, invoice: dict[str, Any]) -> dict[str, Any]:
        contact = invoice.get("contact")
        if isinstance(contact, dict) and (contact.get("vatNumber") or contact.get("name")):
            return invoice
        contact_id = _ref_id(contact)
        if not contact_id:
            return invoice
        cached = self._contact_cache.get(contact_id)
        if cached is None:
            cached = {}
            try:
                payload = self._connection.get(f"/Contact/{contact_id}").json()
                obj = payload.get("objects", payload) if isinstance(payload, dict) else {}
                if isinstance(obj, list):
                    obj = obj[0] if obj else {}
                if isinstance(obj, dict):
                    cached = obj
            except Exception as exc:
                logger.debug("ZM contact fallback failed for %s: %s", contact_id, exc)
            self._contact_cache[contact_id] = cached
        if not cached:
            return invoice
        enriched = dict(invoice)
        enriched["contact"] = cached
        return enriched

    def load_positions(self, resource: str, document_id: str) -> list[dict[str, Any]]:
        doc_id = str(document_id or "").strip()
        if not doc_id:
            return []
        cache_key = (resource, doc_id)
        if cache_key in self._position_cache:
            return [dict(item) for item in self._position_cache[cache_key]]
        path = ""
        params: dict[str, Any] = {"embed": "part"}
        if resource == "Invoice":
            path = "/InvoicePos"
            params.update({"invoice[id]": doc_id, "invoice[objectName]": "Invoice"})
        elif resource == "CreditNote":
            path = "/CreditNotePos"
            params.update({"creditNote[id]": doc_id, "creditNote[objectName]": "CreditNote"})
        else:
            self._position_cache[cache_key] = []
            return []
        try:
            payload = self._connection.get(path, params=params).json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            positions = [item for item in objects if isinstance(item, dict)] if isinstance(objects, list) else []
        except Exception as exc:
            logger.debug("ZM position lookup failed for %s/%s: %s", resource, doc_id, exc)
            positions = []
        self._position_cache[cache_key] = [dict(item) for item in positions]
        return positions


class ZmService:
    """Build the monthly ZM using legacy-compatible invoice-date selection."""

    def __init__(self, provider: ZmInvoiceProvider) -> None:
        self._provider = provider

    def calculate_month(self, year: int, month: int) -> ZmCalculationResult:
        invoices = self._provider.load_invoices(year, month)
        load_credit_notes = getattr(self._provider, "load_credit_notes", None)
        credit_notes = load_credit_notes(year, month) if callable(load_credit_notes) else []
        result = ZmCalculationResult(year=year, month=month, considered=len(invoices) + len(credit_notes))
        buckets: dict[tuple[str, ZmKind], _Bucket] = {}

        def collect_document(
            document: dict[str, Any],
            *,
            resource: str,
            date_key: str,
            amount_sign: Decimal,
        ) -> None:
            if not _is_final_status(document):
                return
            document_date = _parse_date(document.get(date_key) or document.get("date"))
            if document_date is None or document_date.year != year or document_date.month != month:
                return
            if not _has_positions(document) and _classify_zm_kind(document) is not None:
                loader = getattr(self._provider, "load_positions", None)
                doc_id = _ref_id(document.get("id"))
                if callable(loader) and doc_id:
                    positions = loader(resource, doc_id)
                    if positions:
                        if _positions_match_document_total(document, positions):
                            document = dict(document)
                            document["xw_positions"] = positions
                        else:
                            number = str(
                                document.get("invoiceNumber")
                                or document.get("creditNoteNumber")
                                or document.get("number")
                                or doc_id
                            ).strip()
                            result.warnings.append(
                                "ZM-Positionssumme weicht von Dokumentnetto ab; "
                                f"Dokumentnetto verwendet: {number}"
                            )
            facts = _iter_zm_facts(document)
            if not facts:
                return
            result.selected += 1

            contact_raw = document.get("contact")
            contact: dict[str, Any] = contact_raw if isinstance(contact_raw, dict) else {}
            customer = str(contact.get("name") or document.get("contactName") or "").strip()
            document_number = str(
                document.get("invoiceNumber")
                or document.get("creditNoteNumber")
                or document.get("number")
                or document.get("id")
                or ""
            ).strip()
            uid_raw = str(contact.get("vatNumber") or "").strip()
            uid = normalize_uid(uid_raw)
            if not uid or not is_valid_uid(uid):
                label = f"{customer or 'Unbekannter Kunde'}"
                if document_number:
                    label += f" ({document_number})"
                result.invalid.append(f"ungueltige/fehlende UID: {label} -> {uid_raw or 'leer'}")
                return

            for kind, net_amount in facts:
                amount = net_amount * amount_sign
                key = (uid, kind)
                current = buckets.get(key)
                if current is None:
                    buckets[key] = _Bucket(
                        amount=amount,
                        invoices=[document_number] if document_number else [],
                        customer=customer,
                    )
                    continue
                invoices_for_bucket = list(current.invoices)
                if document_number and document_number not in invoices_for_bucket:
                    invoices_for_bucket.append(document_number)
                buckets[key] = _Bucket(
                    amount=current.amount + amount,
                    invoices=invoices_for_bucket,
                    customer=current.customer or customer,
                )

        for invoice in invoices:
            collect_document(invoice, resource="Invoice", date_key="invoiceDate", amount_sign=Decimal("1.00"))
        for credit_note in credit_notes:
            collect_document(
                credit_note,
                resource="CreditNote",
                date_key="creditNoteDate",
                amount_sign=Decimal("-1.00"),
            )

        rows: list[ZmRow] = []
        for (uid, kind), bucket in sorted(buckets.items()):
            rounded = round_commercial(bucket.amount)
            if rounded == 0:
                result.warnings.append(f"ZM-Zeile mit Rundungsbetrag 0 ignoriert: {uid}")
                continue
            rows.append(
                ZmRow(
                    uid=uid,
                    amount_eur_int=rounded,
                    kind=kind,
                    invoice_numbers=bucket.invoices,
                    customer=bucket.customer,
                )
            )
        result.rows = rows
        result.total_eur_int = sum(row.amount_eur_int for row in rows)
        return result

    def render_preview_text(self, result: ZmCalculationResult) -> str:
        lines = [
            "Zusammenfassende Meldung (ZM/U13)",
            f"Periode: {result.year:04d}-{result.month:02d}",
            "Berechnungsart: Soll (Rechnungsdatum)",
            f"Gepruefte Belege: {result.considered}",
            f"ZM-relevante Rechnungen: {result.selected}",
            f"UID-Zeilen: {len(result.rows)}",
            f"Gesamtsumme gerundet: {result.total_eur_int} EUR",
        ]
        if result.rows:
            lines.append("")
            lines.append("--- ZM-Zeilen ---")
            for row in result.rows:
                marker = {"delivery": "Lieferung", "service": "Sonstige Leistung", "dreieck": "Dreieck"}[row.kind]
                inv = f" ({', '.join(row.invoice_numbers)})" if row.invoice_numbers else ""
                lines.append(f"{row.uid} | {marker}: {row.amount_eur_int} EUR{inv}")
        if result.invalid:
            lines.append("")
            lines.append("--- Blockierend vor Upload ---")
            lines.extend(result.invalid)
        if result.warnings:
            lines.append("")
            lines.append("--- Hinweise ---")
            lines.extend(result.warnings)
        return "\n".join(lines)


def normalize_uid(uid: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(uid or "").upper())


def is_valid_uid(uid: str) -> bool:
    if not uid:
        return False
    if uid.startswith("AT"):
        return False
    try:
        return bool(vat.is_valid(uid))
    except Exception:
        return False


def pick_net(invoice: dict[str, Any]) -> Decimal:
    for key in ("sumNet", "sumNetAccounting"):
        value = invoice.get(key)
        if value not in (None, "", 0, "0", "0.0", "0.00"):
            return _to_decimal(value)
    return Decimal("0.00")


def _iter_zm_facts(document: dict[str, Any]) -> list[tuple[ZmKind, Decimal]]:
    positions = document.get("xw_positions")
    if isinstance(positions, list) and positions:
        facts: list[tuple[ZmKind, Decimal]] = []
        for position in positions:
            if not isinstance(position, dict):
                continue
            merged = dict(document)
            for key in ("taxText", "taxRule", "taxType", "taxSet"):
                if position.get(key) not in (None, "", {}, []):
                    merged[key] = position.get(key)
            kind = _classify_zm_kind(merged)
            if kind is None:
                continue
            net = _pick_position_net(position)
            if net != Decimal("0.00"):
                facts.append((kind, net))
        if facts:
            return facts

    kind = _classify_zm_kind(document)
    if kind is None:
        return []
    return [(kind, pick_net(document))]


def _has_positions(document: dict[str, Any]) -> bool:
    positions = document.get("xw_positions")
    return isinstance(positions, list) and bool(positions)


def _positions_match_document_total(document: dict[str, Any], positions: list[dict[str, Any]]) -> bool:
    document_net = abs(pick_net(document))
    if document_net == Decimal("0.00"):
        return True
    position_net = sum(abs(_pick_position_net(position)) for position in positions)
    return abs(position_net - document_net) <= Decimal("0.05")


def _pick_position_net(position: dict[str, Any]) -> Decimal:
    for key in ("sumNet", "sumNetAccounting", "amountNet", "priceNet", "priceNetAccounting", "net"):
        value = position.get(key)
        if value not in (None, "", 0, "0", "0.0", "0.00"):
            return _to_decimal(value)
    quantity = _to_decimal(position.get("quantity") or 1)
    price = _to_decimal(position.get("price") or 0)
    return (quantity * price).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)


def round_commercial(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def _month_timestamp_bounds(year: int, month: int) -> tuple[int, int]:
    start = datetime(year, month, 1)
    end = datetime(year + (month // 12), (month % 12) + 1, 1)
    return int(start.timestamp()), int(end.timestamp()) - 1


def _is_final_status(invoice: dict[str, Any]) -> bool:
    try:
        return int(invoice.get("status") or 0) >= 100
    except (TypeError, ValueError):
        return False


def _classify_zm_kind(invoice: dict[str, Any]) -> ZmKind | None:
    tax_rule = _ref_id(invoice.get("taxRule"))
    tax_type = str(invoice.get("taxType") or "").strip().lower()
    text = " ".join(str(invoice.get("taxText") or "").upper().split())

    if "DREIECK" in text:
        return "dreieck"
    if tax_rule in {"5", "21"} or "REVERSE CHARGE" in text or "SONSTIGE LEISTUNG" in text:
        return "service"
    if "MEHRWERTSTEUER" in text or re.search(r"\b\d+(?:[.,]\d+)?\s*%", text):
        return None
    if tax_type == "eu" or tax_rule == "3" or ("INNERGEMEINSCHAFT" in text and "LIEFER" in text):
        return "delivery"
    return None


def _ref_id(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("id") or value.get("value")
    return str(value or "").strip()


def _parse_date(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _to_decimal(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value).strip().replace(" ", "").replace(",", ".")).quantize(
            _DECIMAL_2,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
