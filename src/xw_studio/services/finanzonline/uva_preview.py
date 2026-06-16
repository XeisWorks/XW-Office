"""Phase 1 UVA preview: legacy-style VAT summary grouped by tax labels."""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Protocol

from pydantic import BaseModel, Field

from xw_studio.services.finanzonline.uva_selection import (
    UvaDocumentSelector,
    UvaSelectionStats,
)
from xw_studio.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)

_DECIMAL_2 = Decimal("0.01")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_FOREIGN_MARKERS = (
    "DEUTSCHE",
    "ITALIENISCHE",
    "SPANISCHE",
    "FRANZÖSISCHE",
    "FRANZOESISCHE",
    "LUXEMBURGISCHE",
    "SCHWEDISCHE",
    "NIEDERLÄNDISCHE",
    "NIEDERLAENDISCHE",
    "BELGISCHE",
    "FINNISCHE",
    "DÄNISCHE",
    "DAENISCHE",
    "SLOWENISCHE",
    "TSCHECHISCHE",
    "IVA",
    "TVA",
    "MOMS",
    "BTW",
    "PVM",
    "DPH",
    "DDV",
)
_EXPORT_TAX_RULES = {"2"}
_ICS_TAX_RULES = {"3"}
_REVERSE_TAX_RULES = {"5", "21"}
_EXPORT_TAXSETS = {"45412"}
_ICS_TAXSETS = {"27267"}
_REVERSE_TAXSETS = {"35315"}
_PAYMENT_DATE_KEYS = (
    "xw_payment_date",
    "paidDate",
    "paymentDate",
    "payDate",
    "datePaid",
    "datePayment",
)
_SALES_DOCUMENT_DATE_KEYS = ("invoiceDate", "date")
_CREDIT_NOTE_DOCUMENT_DATE_KEYS = ("creditNoteDate", "date")
_PURCHASE_DOCUMENT_DATE_KEYS = ("voucherDate", "date")
_PAYMENT_EVENT_DATE_KEYS = ("bookingDate", "valueDate", "entryDate", "date", "created", "create")
_PAYMENT_EVENT_AMOUNT_KEYS = (
    "amountPaid",
    "assignedAmount",
    "assignedAmountGross",
    "paymentAmount",
    "amount",
    "value",
    "sum",
)
_DOCUMENT_AMOUNT_KEYS = (
    "sumGross",
    "sumGrossAccounting",
    "sumGrossForeignCurrency",
    "sumNet",
    "sumNetAccounting",
    "sumTax",
    "sumTaxAccounting",
)
_POSITION_AMOUNT_KEYS = (
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
)


class UvaPreviewGroup(BaseModel):
    """One VAT group shown in the preview."""

    label: str
    vat_amount: str
    gross_amount: str
    net_amount: str


class UvaPreviewSection(BaseModel):
    """Sales or input-tax preview section."""

    total_vat: str
    total_gross: str
    total_net: str
    groups: list[UvaPreviewGroup] = Field(default_factory=list)


class UvaPreviewResult(BaseModel):
    """Human-readable phase-1 preview model."""

    year: int
    month: int
    sales: UvaPreviewSection
    input_tax: UvaPreviewSection
    sales_stats: UvaSelectionStats = Field(default_factory=UvaSelectionStats)
    input_tax_stats: UvaSelectionStats = Field(default_factory=UvaSelectionStats)
    warnings: list[str] = Field(default_factory=list)


class UvaPreviewProvider(Protocol):
    """Abstract source for preview documents."""

    def load_sales_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        ...

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        ...


class SevdeskUvaPreviewProvider:
    """Best-effort preview provider using sevDesk list endpoints."""

    def __init__(
        self,
        connection: SevdeskConnection,
        *,
        page_size: int = 1000,
        max_pages: int = 100,
    ) -> None:
        self._connection = connection
        self._page_size = page_size
        self._max_pages = max_pages
        self._payment_cache: dict[tuple[str, str, int, int], tuple[str | None, str | None]] = {}
        self._position_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._tax_set_text_cache: dict[str, str] = {}

    def load_sales_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        start_ts, end_ts = self._month_bounds(year, month)
        invoice_docs = self._merge_documents(
            self._load_resource(
                "/Invoice",
                params={"startDate": start_ts, "endDate": end_ts, "showAll": "true"},
            ),
            self._filter_documents_by_period_date(
                self._load_resource(
                    "/Invoice",
                    params={"startPayDate": start_ts, "endPayDate": end_ts, "showAll": "true"},
                ),
                year,
                month,
                _PAYMENT_DATE_KEYS,
            ),
            self._load_period_overlay("Invoice", year, month, statuses=("750", "1000")),
            self._load_period_overlay(
                "Invoice",
                year,
                month,
                statuses=(),
                extra_params={"partiallyPaid": "true"},
            ),
        )
        credit_note_docs = self._merge_documents(
            self._load_resource(
                "/CreditNote",
                params={"startDate": start_ts, "endDate": end_ts, "showAll": "true"},
            ),
            self._filter_documents_by_period_date(
                self._load_resource(
                    "/CreditNote",
                    params={"startPayDate": start_ts, "endPayDate": end_ts, "showAll": "true"},
                ),
                year,
                month,
                _PAYMENT_DATE_KEYS,
            ),
            self._load_period_overlay("CreditNote", year, month, statuses=("750", "1000")),
        )

        result: list[dict[str, Any]] = []
        result.extend(
            self._select_sales_resource(
                "Invoice",
                invoice_docs,
                year,
                month,
                document_date_keys=_SALES_DOCUMENT_DATE_KEYS,
            )
        )
        result.extend(
            self._select_sales_resource(
                "CreditNote",
                credit_note_docs,
                year,
                month,
                document_date_keys=_CREDIT_NOTE_DOCUMENT_DATE_KEYS,
                negative_amounts=True,
            )
        )
        return result

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        start_ts, end_ts = self._month_bounds(year, month)
        docs = self._merge_documents(
            self._load_resource(
                "/Voucher",
                params={"year": str(year), "month": str(month), "showAll": "true"},
            ),
            self._filter_documents_by_period_date(
                self._load_resource(
                    "/Voucher",
                    params={"startPayDate": start_ts, "endPayDate": end_ts, "showAll": "true"},
                ),
                year,
                month,
                _PAYMENT_DATE_KEYS,
            ),
            self._load_period_overlay("Voucher", year, month, statuses=("150", "750", "1000")),
        )
        result: list[dict[str, Any]] = []
        for doc in docs:
            enriched = self._enrich_payment_metadata("Voucher", doc, year, month)
            payment_in_period = self._is_period_match(enriched, year, month, _PAYMENT_DATE_KEYS)
            document_in_period = self._is_period_match(enriched, year, month, _PURCHASE_DOCUMENT_DATE_KEYS)
            if not payment_in_period and not document_in_period:
                continue
            credit_debit = str(enriched.get("creditDebit") or "").upper().strip()
            if credit_debit and credit_debit != "C":
                continue
            result.append(self._prepare_document("Voucher", enriched))
        return result

    def _load_resource(self, path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        page_count = 0
        while page_count < self._max_pages:
            query = {"limit": self._page_size, "offset": offset}
            if params:
                query.update(params)
            response = self._connection.get(path, params=query)
            payload = response.json()
            objects = payload.get("objects")
            if not isinstance(objects, list) or not objects:
                break
            result.extend(obj for obj in objects if isinstance(obj, dict))
            page_count += 1
            if len(objects) < self._page_size:
                break
            offset += self._page_size
        return result

    def _prepare_document(self, resource: str, document: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(document)
        self._apply_tax_text_fallback(prepared)
        doc_id = str(prepared.get("id") or "").strip()
        if doc_id:
            positions = self._load_positions(resource, doc_id)
            if positions:
                if resource == "CreditNote":
                    positions = [_with_negative_amounts(position, _POSITION_AMOUNT_KEYS) for position in positions]
                prepared["xw_positions"] = positions
        return prepared

    def _select_sales_resource(
        self,
        resource: str,
        documents: list[dict[str, Any]],
        year: int,
        month: int,
        *,
        document_date_keys: tuple[str, ...],
        negative_amounts: bool = False,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for doc in documents:
            enriched = self._enrich_payment_metadata(resource, doc, year, month)
            payment_in_period = self._is_period_match(enriched, year, month, _PAYMENT_DATE_KEYS)
            document_in_period = self._is_period_match(enriched, year, month, document_date_keys)
            if not payment_in_period and not document_in_period:
                continue
            status = str(enriched.get("status") or "").strip()
            if status and status not in {"1000", "300", "750"} and not payment_in_period:
                continue
            prepared = _with_negative_amounts(enriched, _DOCUMENT_AMOUNT_KEYS) if negative_amounts else enriched
            result.append(self._prepare_document(resource, prepared))
        return result

    @staticmethod
    def _filter_documents_by_period_date(
        documents: list[dict[str, Any]],
        year: int,
        month: int,
        date_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        keep_undated = len(documents) <= 500
        filtered: list[dict[str, Any]] = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            parsed_dates = [_parse_date(document.get(key)) for key in date_keys]
            if any(parsed is not None and parsed.year == year and parsed.month == month for parsed in parsed_dates):
                filtered.append(document)
                continue
            if keep_undated and all(parsed is None for parsed in parsed_dates):
                filtered.append(document)
        return filtered

    def _apply_tax_text_fallback(self, document: dict[str, Any]) -> None:
        raw = str(document.get("taxText") or "").strip()
        if raw and raw not in {"-", "0", "0%", "0.0", "0,0"}:
            return
        tax_set_id = _get_reference_id(document.get("taxSet"))
        if not tax_set_id:
            return
        text = self._fetch_tax_set_text(tax_set_id)
        if text:
            document["taxText"] = text

    def _fetch_tax_set_text(self, tax_set_id: str) -> str:
        if tax_set_id in self._tax_set_text_cache:
            return self._tax_set_text_cache[tax_set_id]
        text = ""
        try:
            payload = self._connection.get(f"/TaxSet/{tax_set_id}").json()
            obj = payload.get("objects", payload) if isinstance(payload, dict) else payload
            if isinstance(obj, list):
                obj = obj[0] if obj else {}
            if isinstance(obj, dict):
                for key in ("text", "taxText", "name", "displayName"):
                    value = str(obj.get(key) or "").strip()
                    if value:
                        text = value
                        break
        except Exception as exc:
            logger.debug("TaxSet lookup failed for %s: %s", tax_set_id, exc)
        self._tax_set_text_cache[tax_set_id] = text
        return text

    def _load_positions(self, resource: str, doc_id: str) -> list[dict[str, Any]]:
        cache_key = (resource, doc_id)
        if cache_key in self._position_cache:
            return self._position_cache[cache_key]
        path = ""
        params: dict[str, Any] = {"embed": "part"}
        if resource == "Invoice":
            path = "/InvoicePos"
            params.update({"invoice[id]": doc_id, "invoice[objectName]": "Invoice"})
        elif resource == "CreditNote":
            path = "/CreditNotePos"
            params.update({"creditNote[id]": doc_id, "creditNote[objectName]": "CreditNote"})
        elif resource == "Voucher":
            path = "/VoucherPos"
            params.update({"voucher[id]": doc_id, "voucher[objectName]": "Voucher"})
        else:
            self._position_cache[cache_key] = []
            return []
        try:
            payload = self._connection.get(path, params=params).json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            positions = [item for item in objects if isinstance(item, dict)] if isinstance(objects, list) else []
        except Exception as exc:
            logger.debug("Position lookup failed for %s/%s: %s", resource, doc_id, exc)
            positions = []
        self._position_cache[cache_key] = positions
        return positions

    @staticmethod
    def _month_bounds(year: int, month: int) -> tuple[int, int]:
        period_start = datetime(year, month, 1)
        period_end = datetime(year + (month // 12), (month % 12) + 1, 1)
        return int(period_start.timestamp()), int(period_end.timestamp()) - 1

    def _load_period_overlay(
        self,
        resource: str,
        year: int,
        month: int,
        *,
        statuses: tuple[str, ...],
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        start_ts, end_ts = self._month_bounds(year, month)
        period_start = datetime.fromtimestamp(start_ts) - timedelta(days=7)
        period_end = datetime.fromtimestamp(end_ts + 1) + timedelta(days=6)
        base_params: dict[str, Any] = {
            "updateAfter": int(period_start.timestamp()),
            "updateBefore": int(period_end.timestamp()) - 1,
            "showAll": "true",
        }
        if extra_params:
            base_params.update(extra_params)

        batches: list[dict[str, Any]] = []
        if statuses:
            for status in statuses:
                params = dict(base_params)
                params["status"] = status
                batches.extend(self._load_resource(f"/{resource}", params=params))
        else:
            batches.extend(self._load_resource(f"/{resource}", params=base_params))
        return batches

    @staticmethod
    def _merge_documents(*batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for batch in batches:
            for doc in batch:
                if not isinstance(doc, dict):
                    continue
                doc_id = str(doc.get("id") or "").strip()
                if not doc_id:
                    continue
                base = dict(merged.get(doc_id, {}))
                for key, value in doc.items():
                    if value not in (None, "", [], {}):
                        base[key] = value
                merged[doc_id] = base
        return list(merged.values())

    def _enrich_payment_metadata(
        self,
        resource: str,
        document: dict[str, Any],
        year: int,
        month: int,
    ) -> dict[str, Any]:
        if self._is_period_match(document, year, month, _PAYMENT_DATE_KEYS):
            return document
        if not _looks_paid_like(document):
            return document
        doc_id = document.get("id")
        if doc_id in (None, ""):
            return document

        cache_key = (resource, str(doc_id), year, month)
        if cache_key not in self._payment_cache:
            self._payment_cache[cache_key] = self._load_payment_metadata(resource, str(doc_id), year, month)
        payment_date, paid_amount = self._payment_cache[cache_key]
        if payment_date is None and paid_amount is None:
            return document

        enriched = dict(document)
        if payment_date is not None:
            enriched["xw_payment_date"] = payment_date
        if paid_amount is not None:
            enriched["xw_paid_amount"] = paid_amount
        return enriched

    def _load_payment_metadata(self, resource: str, doc_id: str, year: int, month: int) -> tuple[str | None, str | None]:
        events: list[dict[str, Any]] = []
        for suffix in ("getCheckAccountTransactionLogs", "getCheckAccountTransactions"):
            try:
                response = self._connection.get(f"/{resource}/{doc_id}/{suffix}")
                payload = response.json()
            except Exception as exc:
                logger.debug("Payment metadata lookup failed for %s/%s via %s: %s", resource, doc_id, suffix, exc)
                continue
            objects = payload.get("objects") if isinstance(payload, dict) else None
            if isinstance(objects, list):
                events.extend(item for item in objects if isinstance(item, dict))

        if not events:
            return None, None

        any_payment_date: datetime | None = None
        period_payment_date: datetime | None = None
        period_paid_amount = Decimal("0.00")

        for event in events:
            event_date = _extract_payment_event_date(event)
            if event_date is not None and (any_payment_date is None or event_date > any_payment_date):
                any_payment_date = event_date
            if event_date is None or event_date.year != year or event_date.month != month:
                continue
            if period_payment_date is None or event_date > period_payment_date:
                period_payment_date = event_date
            amount = _extract_payment_event_amount(event)
            if amount > Decimal("0.00"):
                period_paid_amount += amount

        payment_date = period_payment_date or any_payment_date
        payment_date_text = payment_date.isoformat() if payment_date is not None else None
        paid_amount_text = _format_plain(period_paid_amount) if period_paid_amount > Decimal("0.00") else None
        return payment_date_text, paid_amount_text

    @staticmethod
    def _is_period_match(
        document: dict[str, Any],
        year: int,
        month: int,
        date_keys: tuple[str, ...],
    ) -> bool:
        for key in date_keys:
            value = document.get(key)
            dt = _parse_date(value)
            if dt is not None and dt.year == year and dt.month == month:
                return True
        return False


class UvaPreviewService:
    """Build a legacy-like grouped VAT preview for the selected month."""

    def __init__(
        self,
        provider: UvaPreviewProvider | None = None,
        selector: UvaDocumentSelector | None = None,
    ) -> None:
        self._provider = provider
        self._selector = selector or UvaDocumentSelector()

    def build_preview(self, year: int, month: int) -> UvaPreviewResult:
        sales_docs = self._provider.load_sales_documents(year, month) if self._provider is not None else []
        purchase_docs = self._provider.load_purchase_documents(year, month) if self._provider is not None else []
        sales_selection = self._selector.select_sales_documents(year, month, sales_docs)
        purchase_selection = self._selector.select_purchase_documents(year, month, purchase_docs)
        return UvaPreviewResult(
            year=year,
            month=month,
            sales=self._build_section(sales_selection.documents, is_purchase=False),
            input_tax=self._build_section(purchase_selection.documents, is_purchase=True),
            sales_stats=sales_selection.stats,
            input_tax_stats=purchase_selection.stats,
            warnings=[*sales_selection.warnings, *purchase_selection.warnings],
        )

    def render_preview_text(self, preview: UvaPreviewResult) -> str:
        sales_lines = self._render_section(
            title="Mehrwertsteuer",
            tax_label="Mehrwertsteuer",
            section=preview.sales,
        )
        input_lines = self._render_section(
            title="Vorsteuer",
            tax_label="Vorsteuer",
            section=preview.input_tax,
        )
        lines = sales_lines + ["", ""] + input_lines
        if preview.warnings:
            lines.extend(["", "", "Hinweise:"])
            lines.extend(f"- {warning}" for warning in preview.warnings)
        return "\n".join(lines).strip()

    def _build_section(self, documents: list[dict[str, Any]], *, is_purchase: bool) -> UvaPreviewSection:
        groups: OrderedDict[str, dict[str, Decimal]] = OrderedDict()
        total_vat = Decimal("0.00")
        total_gross = Decimal("0.00")
        total_net = Decimal("0.00")

        for document in documents:
            for label, gross_amount, net_amount, vat_amount in _iter_preview_items(document, is_purchase=is_purchase):
                bucket = groups.setdefault(
                    label,
                    {"vat": Decimal("0.00"), "gross": Decimal("0.00"), "net": Decimal("0.00")},
                )
                bucket["vat"] += vat_amount
                bucket["gross"] += gross_amount
                bucket["net"] += net_amount
                total_vat += vat_amount
                total_gross += gross_amount
                total_net += net_amount

        group_models = [
            UvaPreviewGroup(
                label=label,
                vat_amount=_format_plain(values["vat"]),
                gross_amount=_format_plain(values["gross"]),
                net_amount=_format_plain(values["net"]),
            )
            for label, values in groups.items()
        ]
        return UvaPreviewSection(
            total_vat=_format_plain(total_vat),
            total_gross=_format_plain(total_gross),
            total_net=_format_plain(total_net),
            groups=group_models,
        )

    @staticmethod
    def _render_section(title: str, tax_label: str, section: UvaPreviewSection) -> list[str]:
        lines = [
            title,
            f"EUR {_format_euro_text(section.total_vat)}",
            "",
            f"Brutto: EUR {_format_euro_text(section.total_gross)}",
            f"Netto: EUR {_format_euro_text(section.total_net)}",
        ]
        for group in section.groups:
            lines.extend(["", group.label])
            is_sales_ig_delivery = (
                title == "Mehrwertsteuer"
                and "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG" in group.label
            )
            if is_sales_ig_delivery:
                lines.append(f"Netto: EUR {_format_euro_text(group.net_amount)}")
                continue
            lines.extend(
                [
                    f"{tax_label}: EUR {_format_euro_text(group.vat_amount)}",
                    f"Brutto: EUR {_format_euro_text(group.gross_amount)}",
                    f"Netto: EUR {_format_euro_text(group.net_amount)}",
                ]
            )
        return lines


def _looks_paid_like(document: dict[str, Any]) -> bool:
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


def _extract_payment_event_date(event: dict[str, Any]) -> datetime | None:
    for node in _payment_event_nodes(event):
        for key in _PAYMENT_EVENT_DATE_KEYS:
            dt = _parse_date(node.get(key))
            if dt is not None:
                return dt
    return None


def _extract_payment_event_amount(event: dict[str, Any]) -> Decimal:
    for node in _payment_event_nodes(event):
        for key in _PAYMENT_EVENT_AMOUNT_KEYS:
            if key not in node:
                continue
            amount = abs(_to_decimal(node.get(key)))
            if amount > Decimal("0.00"):
                return amount
    return Decimal("0.00")


def _payment_event_nodes(event: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [event]
    nested = event.get("checkAccountTransaction")
    if isinstance(nested, dict):
        nodes.append(nested)
    return nodes


def _with_negative_amounts(payload: dict[str, Any], amount_keys: tuple[str, ...]) -> dict[str, Any]:
    prepared = dict(payload)
    for key in amount_keys:
        if key not in prepared or prepared.get(key) in (None, ""):
            continue
        amount = _to_decimal(prepared.get(key))
        if amount > Decimal("0.00"):
            prepared[key] = _format_plain(-amount)
    return prepared


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


def _format_plain(value: Decimal) -> str:
    return f"{value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP):.2f}"


def _format_euro_text(value: str) -> str:
    amount = _to_decimal(value)
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


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


def _extract_amounts(document: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    gross_amount = _first_decimal(document, "sumGross", "sumGrossAccounting", "sumGrossForeignCurrency")
    net_amount = _first_decimal(document, "sumNet", "sumNetAccounting")
    vat_amount = _first_decimal(document, "sumTax", "sumTaxAccounting")

    if net_amount == Decimal("0.00") and gross_amount != Decimal("0.00"):
        net_amount = gross_amount - vat_amount
    if vat_amount == Decimal("0.00") and gross_amount != Decimal("0.00") and net_amount != Decimal("0.00"):
        vat_amount = gross_amount - net_amount
    return gross_amount, net_amount, vat_amount


_ALLOWED_PURCHASE_LABELS = {
    "MIT 0% MEHRWERTSTEUER",
    "MIT 10% MEHRWERTSTEUER",
    "MIT 13% MEHRWERTSTEUER",
    "MIT 20% MEHRWERTSTEUER",
    "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
    "REVERSE CHARGE",
}


def _iter_preview_items(
    document: dict[str, Any],
    *,
    is_purchase: bool,
) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    positions = document.get("xw_positions")
    if isinstance(positions, list) and positions:
        items: list[tuple[str, Decimal, Decimal, Decimal]] = []
        for position in positions:
            if not isinstance(position, dict):
                continue
            gross_amount, net_amount, vat_amount = _extract_position_amounts(position)
            if gross_amount == Decimal("0.00") and net_amount == Decimal("0.00") and vat_amount == Decimal("0.00"):
                continue
            label = _normalize_position_label(
                position,
                document,
                net_amount=net_amount,
                vat_amount=vat_amount,
                is_purchase=is_purchase,
            )
            if label is None:
                continue
            items.append((label, gross_amount, net_amount, vat_amount))
        if items:
            return items

    gross_amount, net_amount, vat_amount = _extract_amounts(document)
    label = _normalize_tax_label(document, net_amount=net_amount, vat_amount=vat_amount)
    if is_purchase and label not in _ALLOWED_PURCHASE_LABELS:
        return []
    return [(label, gross_amount, net_amount, vat_amount)]


def _extract_position_amounts(position: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    net_amount = _first_position_decimal(
        position,
        "sumNetAccounting",
        "sumNet",
        "amountNet",
        "priceNet",
        "priceNetAccounting",
        "net",
    )
    vat_amount = _first_position_decimal(position, "sumTaxAccounting", "sumTax")
    if net_amount == Decimal("0.00"):
        quantity = _to_decimal(position.get("quantity") or 1)
        price = _to_decimal(position.get("price") or 0)
        net_amount = quantity * price
    if vat_amount == Decimal("0.00") and net_amount != Decimal("0.00"):
        rate = _extract_position_rate(position)
        if rate > Decimal("0.00"):
            vat_amount = (net_amount * rate / Decimal("100")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    gross_amount = (net_amount + vat_amount).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    return gross_amount, net_amount, vat_amount


def _first_position_decimal(position: dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        if key in position and position.get(key) not in (None, ""):
            return _to_decimal(position.get(key))
    return Decimal("0.00")


def _extract_position_rate(position: dict[str, Any]) -> Decimal:
    for key in ("taxRate", "taxRatePercent", "taxRatePercentage", "taxPercent", "taxPercentage"):
        value = position.get(key)
        if value not in (None, ""):
            return _to_decimal(value)
    tax_node = position.get("tax")
    if isinstance(tax_node, dict):
        for key in ("rate", "percentage"):
            value = tax_node.get(key)
            if value not in (None, ""):
                return _to_decimal(value)
    return Decimal("0.00")


def _normalize_position_label(
    position: dict[str, Any],
    document: dict[str, Any],
    *,
    net_amount: Decimal,
    vat_amount: Decimal,
    is_purchase: bool,
) -> str | None:
    merged = dict(document)
    if position.get("taxText") not in (None, ""):
        merged["taxText"] = position.get("taxText")
    label = _normalize_tax_label(merged, net_amount=net_amount, vat_amount=vat_amount)
    if is_purchase and label not in _ALLOWED_PURCHASE_LABELS:
        upper = label.upper()
        if "REVERSE" in upper and "CHARGE" in upper:
            return "REVERSE CHARGE"
        if "INNERGEMEINSCHAFT" in upper and "LIEFER" in upper:
            return "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)"
        return None
    return label


def _first_decimal(document: dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        if key in document and document.get(key) not in (None, ""):
            return _to_decimal(document.get(key))
    return Decimal("0.00")


def _normalize_tax_label(document: dict[str, Any], *, net_amount: Decimal, vat_amount: Decimal) -> str:
    raw = " ".join(str(document.get("taxText") or "").split()).strip()
    if raw in {"0", "0%", "0.0", "0,0", "-"}:
        raw = ""

    if raw:
        upper = raw.upper()
        if "REVERSE" in upper and "CHARGE" in upper:
            return "REVERSE CHARGE"
        if "INNERGEMEINSCHAFT" in upper and "LIEFER" in upper:
            return "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)"
        if "AUSFUHR" in upper:
            return "STEUERFREIE AUSFUHRLIEFERUNG (§ 7 USTG 1994)"
        if any(marker in upper for marker in _FOREIGN_MARKERS):
            return upper
        rate = _extract_percent(upper)
        if rate is not None:
            return f"MIT {rate}% MEHRWERTSTEUER"
        return upper

    metadata_label = _classify_special_tax_label(document)
    if metadata_label is not None:
        return metadata_label

    inferred_rate = _infer_rate(net_amount, vat_amount)
    return f"MIT {inferred_rate}% MEHRWERTSTEUER"


def _extract_percent(label: str) -> int | None:
    match = _PERCENT_RE.search(label)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if value == value.to_integral_value():
        return int(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _get_reference_id(value: object) -> str:
    if isinstance(value, dict):
        ref = value.get("id") or value.get("value")
        return str(ref or "").strip()
    return str(value or "").strip()


def _classify_special_tax_label(document: dict[str, Any]) -> str | None:
    tax_rule = _get_reference_id(document.get("taxRule"))
    tax_set = _get_reference_id(document.get("taxSet"))
    tax_type = str(document.get("taxType") or "").strip().lower()

    if tax_rule in _EXPORT_TAX_RULES or tax_set in _EXPORT_TAXSETS:
        return "STEUERFREIE AUSFUHRLIEFERUNG (§ 7 USTG 1994)"
    if tax_rule in _REVERSE_TAX_RULES or tax_set in _REVERSE_TAXSETS:
        return "REVERSE CHARGE"
    if tax_rule in _ICS_TAX_RULES or tax_type == "eu" or tax_set in _ICS_TAXSETS:
        return "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)"
    return None


def _infer_rate(net_amount: Decimal, vat_amount: Decimal) -> int:
    if net_amount == Decimal("0.00") or vat_amount == Decimal("0.00"):
        return 0
    ratio = vat_amount / net_amount * Decimal("100")
    for candidate in (Decimal("10"), Decimal("13"), Decimal("20")):
        if abs(ratio - candidate) <= Decimal("1.5"):
            return int(candidate)
    rounded = ratio.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)
