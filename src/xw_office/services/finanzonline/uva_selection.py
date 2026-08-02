"""Cash-basis document selection helpers for UVA preview/payload generation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from pydantic import BaseModel, Field

_DECIMAL_2 = Decimal("0.01")
_RATIO_QUANT = Decimal("0.0001")
_EPS = Decimal("0.005")
_PAID_DATE_KEYS = (
    "xw_payment_date",
    "paidDate",
    "paymentDate",
    "payDate",
    "datePaid",
    "datePayment",
)
_SALES_FALLBACK_DATE_KEYS = ("invoiceDate", "deliveryDate", "date")
_PURCHASE_FALLBACK_DATE_KEYS = ("voucherDate", "deliveryDate", "date")


class UvaSelectionStats(BaseModel):
    """Audit counters for document selection."""

    considered: int = 0
    selected: int = 0
    partial_scaled: int = 0
    duplicates_removed: int = 0
    cancelled_ignored: int = 0
    draft_or_open_ignored: int = 0
    payment_out_of_period: int = 0
    missing_payment_evidence: int = 0
    future_document_ignored: int = 0


class UvaSelectionResult(BaseModel):
    """Selected documents with warnings and audit stats."""

    documents: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stats: UvaSelectionStats = Field(default_factory=UvaSelectionStats)


class UvaDocumentSelector:
    """Approximate legacy IST-mode selection without the monolithic UVA service."""

    def select_sales_documents(
        self, year: int, month: int, documents: list[dict[str, Any]]
    ) -> UvaSelectionResult:
        return self._select_documents(
            year,
            month,
            documents,
            fallback_date_keys=_SALES_FALLBACK_DATE_KEYS,
            dedupe=False,
        )

    def select_purchase_documents(
        self, year: int, month: int, documents: list[dict[str, Any]]
    ) -> UvaSelectionResult:
        return self._select_documents(
            year,
            month,
            documents,
            fallback_date_keys=_PURCHASE_FALLBACK_DATE_KEYS,
            dedupe=True,
            reject_future_documents=True,
        )

    def _select_documents(
        self,
        year: int,
        month: int,
        documents: list[dict[str, Any]],
        *,
        fallback_date_keys: tuple[str, ...],
        dedupe: bool,
        reject_future_documents: bool = False,
    ) -> UvaSelectionResult:
        result = UvaSelectionResult()
        selected: list[dict[str, Any]] = []

        for document in documents:
            if not isinstance(document, dict):
                continue
            result.stats.considered += 1
            payment_date = _first_date(document, _PAID_DATE_KEYS)
            fallback_date = _first_date(document, fallback_date_keys)
            payment_in_period = _is_in_period(payment_date, year, month)
            fallback_in_period = _is_in_period(fallback_date, year, month)
            label = _doc_label(document)

            # sevDesk may expose a payDate that precedes the voucher itself. Such
            # a future-dated purchase cannot belong to an earlier UVA period,
            # even when that implausible payDate happens to fall into the month.
            if (
                reject_future_documents
                and fallback_date is not None
                and (fallback_date.year, fallback_date.month)
                > (
                    year,
                    month,
                )
            ):
                result.stats.future_document_ignored += 1
                result.warnings.append(
                    f"Zukuenftiger Eingangsbeleg trotz frueherem Zahlungsdatum ignoriert: {label}"
                )
                continue

            if payment_date is None and fallback_date is None:
                if label == "unbekannt":
                    scaled_document, scaled = _scale_document_to_paid_ratio(document)
                    if scaled:
                        result.stats.partial_scaled += 1
                        result.warnings.append(f"Teilzahlung anteilig berücksichtigt: {label}")
                    selected.append(scaled_document)
                    result.stats.selected += 1
                    continue
                result.stats.missing_payment_evidence += 1
                result.warnings.append(
                    f"Ohne Zahlungsnachweis im IST-Modus nicht übernommen: {label}"
                )
                continue

            if _is_cancelled(document) and not payment_in_period:
                result.stats.cancelled_ignored += 1
                result.warnings.append(f"Stornierter Beleg ohne Periodenzahlung ignoriert: {label}")
                continue

            if _is_open_or_draft(document) and not payment_in_period:
                result.stats.draft_or_open_ignored += 1
                result.warnings.append(
                    f"Offener/Entwurfs-Beleg ohne Periodenzahlung ignoriert: {label}"
                )
                continue

            if payment_in_period:
                scaled_document, scaled = _scale_document_to_paid_ratio(document)
                if scaled:
                    result.stats.partial_scaled += 1
                    result.warnings.append(f"Teilzahlung anteilig berücksichtigt: {label}")
                if _is_credit_note(document) and not _has_credit_reference(document):
                    result.warnings.append(f"Gutschrift ohne Referenzrechnung erkannt: {label}")
                selected.append(scaled_document)
                result.stats.selected += 1
                continue

            if payment_date is not None:
                result.stats.payment_out_of_period += 1
                result.warnings.append(f"Zahlung liegt außerhalb des UVA-Monats: {label}")
                continue

            if fallback_in_period:
                result.stats.missing_payment_evidence += 1
                result.warnings.append(
                    f"Ohne Zahlungsnachweis im IST-Modus nicht übernommen: {label}"
                )

        if dedupe:
            selected, removed, warnings = self._dedupe_documents(selected)
            result.stats.duplicates_removed += removed
            result.warnings.extend(warnings)
            result.stats.selected = max(0, result.stats.selected - removed)

        result.documents = selected
        result.warnings = _dedupe_warning_lines(result.warnings)
        return result

    def _dedupe_documents(
        self, documents: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int, list[str]]:
        seen: dict[tuple[str, ...], dict[str, Any]] = {}
        deduped: list[dict[str, Any]] = []
        warnings: list[str] = []
        removed = 0

        for document in documents:
            signature = _document_signature(document)
            if signature is None:
                deduped.append(document)
                continue
            if signature in seen:
                removed += 1
                warnings.append(
                    f"Duplikat-Beleg ignoriert: {_doc_label(document)} (bereits übernommen: {_doc_label(seen[signature])})"
                )
                continue
            seen[signature] = document
            deduped.append(document)

        return deduped, removed, warnings


def _dedupe_warning_lines(warnings: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        text = str(warning).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _doc_label(document: dict[str, Any]) -> str:
    for key in ("invoiceNumber", "voucherNumber", "creditNoteNumber", "number", "reference", "id"):
        value = document.get(key)
        if value not in (None, ""):
            return str(value)
    return "unbekannt"


def _is_credit_note(document: dict[str, Any]) -> bool:
    return any(
        key in document
        for key in ("creditNoteNumber", "refSrcInvoice", "refSrcInvoiceId", "refInvoiceId")
    )


def _has_credit_reference(document: dict[str, Any]) -> bool:
    for key in ("refSrcInvoice", "refSrcInvoiceId", "refInvoice", "refInvoiceId", "invoiceId"):
        value = document.get(key)
        if isinstance(value, dict):
            value = value.get("id") or value.get("value")
        if value not in (None, ""):
            return True
    return False


def _is_cancelled(document: dict[str, Any]) -> bool:
    if bool(document.get("cancelled")):
        return True
    status = str(document.get("status") or document.get("statusText") or "").strip().lower()
    return any(marker in status for marker in ("cancel", "storno", "void"))


def _is_open_or_draft(document: dict[str, Any]) -> bool:
    status = str(document.get("status") or document.get("statusText") or "").strip().lower()
    return status in {"100", "200", "draft", "entwurf", "open", "offen"}


def _scale_document_to_paid_ratio(document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    gross = _first_decimal(document, "sumGross", "sumGrossAccounting", "sumGrossForeignCurrency")
    if abs(gross) <= _EPS:
        return dict(document), False

    paid_amount = _extract_paid_amount(document, gross)
    if paid_amount <= _EPS or paid_amount >= (abs(gross) - _EPS):
        return dict(document), False

    ratio = (paid_amount / abs(gross)).quantize(_RATIO_QUANT, rounding=ROUND_HALF_UP)
    if ratio <= Decimal("0.0000") or ratio >= Decimal("0.9999"):
        return dict(document), False

    scaled = dict(document)
    for key in (
        "sumGross",
        "sumGrossAccounting",
        "sumGrossForeignCurrency",
        "sumNet",
        "sumNetAccounting",
        "sumTax",
        "sumTaxAccounting",
    ):
        if key in scaled and scaled.get(key) not in (None, ""):
            scaled[key] = _fmt(_to_decimal(scaled.get(key)) * ratio)
    positions = scaled.get("xw_positions")
    if isinstance(positions, list):
        scaled["xw_positions"] = [
            _scale_position_to_ratio(position, ratio) if isinstance(position, dict) else position
            for position in positions
        ]
    scaled["xw_paid_ratio"] = _fmt(ratio)
    return scaled, True


def _scale_position_to_ratio(position: dict[str, Any], ratio: Decimal) -> dict[str, Any]:
    scaled = dict(position)
    for key in (
        "sumGross",
        "sumGrossAccounting",
        "sumNet",
        "sumNetAccounting",
        "sumTax",
        "sumTaxAccounting",
        "amountNet",
        "priceNet",
        "priceNetAccounting",
        "net",
    ):
        if key in scaled and scaled.get(key) not in (None, ""):
            scaled[key] = _fmt(_to_decimal(scaled.get(key)) * ratio)
    return scaled


def _extract_paid_amount(document: dict[str, Any], gross_amount: Decimal) -> Decimal:
    for key in (
        "xw_paid_amount",
        "xw_period_paid_amount",
        "paidAmount",
        "sumPaid",
        "sumPaidAccounting",
        "paidValue",
    ):
        value = document.get(key)
        amount = _to_decimal(value)
        if amount > _EPS:
            return amount

    for key in ("sumOutstanding", "openAmount", "amountOutstanding"):
        outstanding = _to_decimal(document.get(key))
        if outstanding > Decimal("0.00") and abs(gross_amount) > outstanding:
            return abs(gross_amount) - outstanding

    return abs(gross_amount) if _is_paid_like(document) else Decimal("0.00")


def _is_paid_like(document: dict[str, Any]) -> bool:
    status = str(document.get("status") or document.get("statusText") or "").strip().lower()
    if status in {"300", "750", "1000", "paid", "bezahlt", "partial", "teilweise"}:
        return True
    for key in ("paid", "isPaid", "partiallyPaid", "isPartiallyPaid"):
        value = document.get(key)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "ja"}:
            return True
    return False


def _document_signature(document: dict[str, Any]) -> tuple[str, ...] | None:
    supplier = _identity_text(
        document.get("supplierNameAtSave")
        or document.get("supplierName")
        or document.get("contactName")
        or document.get("name")
        or document.get("addressName")
    )
    number = _identity_text(
        document.get("voucherNumber")
        or document.get("invoiceNumber")
        or document.get("creditNoteNumber")
        or document.get("number")
        or document.get("reference")
    )
    if not supplier or not number:
        return None
    return (
        str(document.get("creditDebit") or "").strip().upper(),
        supplier,
        number,
        _fmt(_first_decimal(document, "sumGross", "sumGrossAccounting", "sumGrossForeignCurrency")),
        _fmt(_first_decimal(document, "sumTax", "sumTaxAccounting")),
        _identity_text(document.get("taxText")),
        str(document.get("currency") or "EUR").strip().upper(),
    )


def _identity_text(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_in_period(value: datetime | None, year: int, month: int) -> bool:
    return value is not None and value.year == year and value.month == month


def _first_date(document: dict[str, Any], keys: tuple[str, ...]) -> datetime | None:
    for key in keys:
        value = document.get(key)
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
    return None


def _parse_date(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
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


def _first_decimal(document: dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        if key in document and document.get(key) not in (None, ""):
            return _to_decimal(document.get(key))
    return Decimal("0.00")


def _to_decimal(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    try:
        text = str(value).strip().replace(" ", "").replace(",", ".")
        return Decimal(text).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP):.2f}"
