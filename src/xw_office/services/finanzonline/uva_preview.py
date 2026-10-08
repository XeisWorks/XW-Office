"""Phase 1 UVA preview: legacy-style VAT summary grouped by tax labels."""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Protocol

from pydantic import BaseModel, Field

from xw_office.services.finanzonline.uva_selection import (
    UvaDocumentSelector,
    UvaSelectionStats,
    _purchase_tax_date,
    _purchase_uses_accrual,
)
from xw_office.services.http_client import SevdeskConnection
from xw_office.services.finanzonline.source_reads import load_tax_resource
from xw_office.services.finanzonline.payment_evidence import SevdeskPaymentEvidence, parse_source_date as _parse_date
from xw_office.services.finanzonline.amounts import (
    tax_amount,
    document_amounts as _extract_amounts,
    position_amounts as _extract_position_amounts,
    position_rate as _extract_position_rate,
)
from xw_office.services.finanzonline.zm_service import is_valid_uid, normalize_uid

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
        self._voucher_period_cache: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self._payment_evidence = SevdeskPaymentEvidence(connection)

    @property
    def payment_warnings(self) -> list[str]:
        return self._payment_evidence.warnings

    def clear_cache(self) -> None:
        """Start a fresh source read without losing reuse within the calculation."""
        self._payment_cache.clear()
        self._position_cache.clear()
        self._tax_set_text_cache.clear()
        self._voucher_period_cache.clear()
        self._payment_evidence.clear()

    def prepare_payment_logs(self) -> None:
        """Read complete assignment history once; keep per-document fallback."""
        self._payment_evidence.prepare()

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

        # sevDesk frequently returns an empty/zero taxText on historical documents
        # although another document with the same TaxSet carries the effective label.
        # Prime the mapping from the complete candidate set before positions are built;
        # this mirrors the proven legacy calculation and avoids classifying those
        # documents as 0% merely because their individual list payload is sparse.
        self._prime_tax_set_text_cache([*invoice_docs, *credit_note_docs])

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
        # sevDesk uses creditDebit=D vouchers for revenue-side tax postings
        # (notably settlement/participation entries). Legacy UVA includes these
        # in A022/A006/A021; treating every Voucher as purchase input tax drops
        # material output VAT.
        voucher_docs = self._load_voucher_candidates(year, month)
        self._prime_tax_set_text_cache(voucher_docs)
        for doc in voucher_docs:
            if str(doc.get("creditDebit") or "").upper().strip() != "D":
                continue
            enriched = self._enrich_payment_metadata("Voucher", doc, year, month)
            if not self._is_period_match(enriched, year, month, _PAYMENT_DATE_KEYS) and not self._is_period_match(
                enriched, year, month, _PURCHASE_DOCUMENT_DATE_KEYS
            ):
                continue
            result.append(self._prepare_document("Voucher", enriched))
        return result

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        docs = self._load_voucher_candidates(year, month)
        self._prime_tax_set_text_cache(docs)
        result: list[dict[str, Any]] = []
        for doc in docs:
            credit_debit = str(doc.get("creditDebit") or "").upper().strip()
            if credit_debit and credit_debit != "C":
                continue
            doc = dict(doc)
            self._apply_tax_text_fallback(doc)
            accrual = _purchase_uses_accrual(doc)
            if accrual:
                enriched = doc
            else:
                enriched = self._enrich_payment_metadata("Voucher", doc, year, month)
            payment_in_period = self._is_period_match(enriched, year, month, _PAYMENT_DATE_KEYS)
            document_in_period = self._is_period_match(enriched, year, month, _PURCHASE_DOCUMENT_DATE_KEYS)
            tax_date = _purchase_tax_date(
                enriched, _parse_date(enriched.get("voucherDate") or enriched.get("date"))
            ) if accrual else None
            accrual_in_period = tax_date is not None and (tax_date.year, tax_date.month) == (year, month)
            if not payment_in_period and not document_in_period and not accrual_in_period:
                continue
            credit_debit = str(enriched.get("creditDebit") or "").upper().strip()
            if credit_debit and credit_debit != "C":
                continue
            result.append(self._prepare_document("Voucher", enriched))
        return result

    def _load_voucher_candidates(self, year: int, month: int) -> list[dict[str, Any]]:
        cache_key = (year, month)
        cached = self._voucher_period_cache.get(cache_key)
        if cached is not None:
            return [dict(document) for document in cached]
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
        self._voucher_period_cache[cache_key] = [dict(document) for document in docs]
        return docs

    def _load_resource(self, path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return load_tax_resource(
            self._connection, path, params=params,
            page_size=self._page_size, max_pages=self._max_pages,
        )

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
        text = self._tax_set_text_cache.get(tax_set_id) or self._fetch_tax_set_text(tax_set_id)
        if text:
            document["taxText"] = text

    def _prime_tax_set_text_cache(self, documents: list[dict[str, Any]]) -> None:
        for document in documents:
            tax_set_id = _get_reference_id(document.get("taxSet"))
            raw = " ".join(str(document.get("taxText") or "").split()).strip()
            if not tax_set_id or raw in {"", "-", "0", "0%", "0.0", "0,0"}:
                continue
            existing = self._tax_set_text_cache.get(tax_set_id)
            if existing and existing.casefold() != raw.casefold():
                logger.warning(
                    "Mehrdeutiger TaxSet-Text %s: %r / %r; erster Wert bleibt aktiv",
                    tax_set_id,
                    existing,
                    raw,
                )
                continue
            self._tax_set_text_cache[tax_set_id] = raw

    def _fetch_tax_set_text(self, tax_set_id: str) -> str:
        if tax_set_id in self._tax_set_text_cache:
            return self._tax_set_text_cache[tax_set_id]
        text = ""
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
        if not text:
            raise ValueError(f"UVA: Steuerzuordnung fuer TaxSet {tax_set_id} fehlt.")
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
        positions = self._load_resource(path, params=params)
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
        period_end = max(
            period_end,
            datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
        )
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
                    raise ValueError("UVA: Beleg ohne eindeutige ID in den Quelldaten.")
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
        expected_paid = next(
            (abs(_to_decimal(document[key])) for key in (
                "paidAmount", "sumPaid", "sumPaidAccounting", "paidValue",
            ) if document.get(key) not in (None, "")),
            None,
        )
        if expected_paid == Decimal("0.00"):
            expected_paid = None
        doc_id = document.get("id")
        bulk_exists = (resource, str(doc_id)) in self._payment_evidence.logs
        fully_paid = str(document.get("status") or "").lower() in {"300", "1000", "paid", "bezahlt"}
        if expected_paid is None and fully_paid and bulk_exists:
            expected_paid = abs(_extract_amounts(document)[0])
        if (
            self._is_period_match(document, year, month, _PAYMENT_DATE_KEYS)
            and expected_paid is None
            and fully_paid
            and (not self._payment_evidence.complete or not bulk_exists)
        ):
            return document
        if not _looks_paid_like(document):
            return document
        if doc_id in (None, ""):
            return document

        cache_key = (resource, str(doc_id), year, month)
        if cache_key not in self._payment_cache:
            self._payment_cache[cache_key] = self._load_payment_metadata(
                resource, str(doc_id), year, month, expected_paid_amount=expected_paid,
                gross_amount=abs(_extract_amounts(document)[0]),
                evidence_date=(
                    _parse_date(document.get("voucherDate") or document.get("date"))
                    if resource == "Voucher" and str(document.get("creditDebit") or "").upper() == "C"
                    else None
                ),
            )
        payment_date, paid_amount = self._payment_cache[cache_key]
        if payment_date is None and paid_amount is None:
            return document

        enriched = dict(document)
        if payment_date is not None:
            enriched["xw_payment_date"] = payment_date
        if paid_amount is not None:
            enriched["xw_paid_amount"] = paid_amount
        return enriched

    def _load_payment_metadata(
        self, resource: str, doc_id: str, year: int, month: int,
        *, expected_paid_amount: Decimal | None = None,
        gross_amount: Decimal | None = None,
        evidence_date: datetime | None = None,
    ) -> tuple[str | None, str | None]:
        return self._payment_evidence.load(
            resource, doc_id, year, month, expected_paid_amount=expected_paid_amount,
            gross_amount=gross_amount, evidence_date=evidence_date,
        )

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
        if isinstance(self._provider, SevdeskUvaPreviewProvider):
            self._provider.clear_cache()
            self._provider.prepare_payment_logs()
        sales_docs = self._provider.load_sales_documents(year, month) if self._provider is not None else []
        purchase_docs = self._provider.load_purchase_documents(year, month) if self._provider is not None else []
        sales_selection = self._selector.select_sales_documents(year, month, sales_docs)
        purchase_selection = self._selector.select_purchase_documents(year, month, purchase_docs)
        warnings = [*sales_selection.warnings, *purchase_selection.warnings]
        if isinstance(self._provider, SevdeskUvaPreviewProvider):
            warnings.extend(self._provider.payment_warnings)
        sales = self._build_section(sales_selection.documents, is_purchase=False, warnings=warnings)
        input_tax = self._build_section(purchase_selection.documents, is_purchase=True, warnings=warnings)
        return UvaPreviewResult(
            year=year,
            month=month,
            sales=sales,
            input_tax=input_tax,
            sales_stats=sales_selection.stats,
            input_tax_stats=purchase_selection.stats,
            warnings=warnings,
        )

    def render_preview_text(self, preview: UvaPreviewResult) -> str:
        sales_lines = self._render_section(
            title="sevDesk Steueranalyse - Mehrwertsteuer (Kontrollansicht)",
            tax_label="Mehrwertsteuer",
            section=preview.sales,
        )
        input_lines = self._render_section(
            title="sevDesk Steueranalyse - Vorsteuer (Kontrollansicht)",
            tax_label="Vorsteuer",
            section=preview.input_tax,
        )
        lines = sales_lines + ["", ""] + input_lines
        if preview.warnings:
            lines.extend(["", "", "Hinweise:"])
            lines.extend(f"- {warning}" for warning in preview.warnings)
        return "\n".join(lines).strip()

    def _build_section(
        self,
        documents: list[dict[str, Any]],
        *,
        is_purchase: bool,
        warnings: list[str] | None = None,
    ) -> UvaPreviewSection:
        groups: OrderedDict[str, dict[str, Decimal]] = OrderedDict()
        total_vat = Decimal("0.00")
        total_gross = Decimal("0.00")
        total_net = Decimal("0.00")

        for document in documents:
            items = _iter_preview_items(document, is_purchase=is_purchase)
            if warnings is not None and document.get("xw_positions"):
                source_gross, source_net, source_vat = _extract_amounts(document)
                position_gross = sum((item[1] for item in items), Decimal(0))
                position_net = sum((item[2] for item in items), Decimal(0))
                position_vat = sum((item[3] for item in items), Decimal(0))
                tolerance = max(Decimal("0.05"), Decimal("0.01") * len(items))
                if source_gross != Decimal(0) and any(
                    abs(source - calculated) > tolerance
                    for source, calculated in (
                        (source_net, position_net),
                        (source_vat, position_vat),
                    )
                ):
                    label = str(document.get("invoiceNumber") or document.get("voucherNumber")
                                or document.get("creditNoteNumber") or document.get("id") or "-")
                    warnings.append(
                        f"Ungeklaerte Positionssumme weicht von Belegsumme ab: {label}"
                    )
                elif source_gross != Decimal(0) and abs(source_gross - position_gross) > tolerance:
                    warnings.append("Belegbrutto enthaelt nicht steuerwirksame Differenz "
                                    f"(z. B. Trinkgeld): {document.get('id') or '-'}")
            for label, gross_amount, net_amount, vat_amount in items:
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
                (title == "Mehrwertsteuer" or title.startswith("sevDesk Steueranalyse - Mehrwertsteuer"))
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
    return tax_amount(value)


def _format_plain(value: Decimal) -> str:
    return f"{value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP):.2f}"


def _format_euro_text(value: str) -> str:
    amount = _to_decimal(value)
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


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
            items.append((_sales_rc_label(label, document, is_purchase=is_purchase),
                          gross_amount, net_amount, vat_amount))
        if items:
            source_gross, source_net, source_vat = _extract_amounts(document)
            tolerance = max(Decimal("0.05"), Decimal("0.01") * len(items))
            if (
                len({item[0] for item in items}) == 1
                and source_gross != Decimal(0)
                and abs(source_gross - source_net - source_vat) <= Decimal("0.01")
                and abs(sum((item[2] for item in items), Decimal(0)) - source_net) <= tolerance
                and abs(sum((item[3] for item in items), Decimal(0)) - source_vat) <= tolerance
            ):
                return [(items[0][0], source_gross, source_net, source_vat)]
            return items

    gross_amount, net_amount, vat_amount = _extract_amounts(document)
    label = _normalize_tax_label(document, net_amount=net_amount, vat_amount=vat_amount)
    return [(_sales_rc_label(label, document, is_purchase=is_purchase),
             gross_amount, net_amount, vat_amount)]


def _sales_rc_label(label: str, document: dict[str, Any], *, is_purchase: bool) -> str:
    if is_purchase or label != "REVERSE CHARGE":
        return label
    contact = document.get("contact")
    contact_uid = contact.get("vatNumber") if isinstance(contact, dict) else None
    uid = normalize_uid(str(contact_uid or document.get("vatNumber") or ""))
    if uid.startswith("AT"):
        return label
    if is_valid_uid(uid):
        return "REVERSE CHARGE (AUSLAND)"
    return "REVERSE CHARGE (ZUORDNUNG OFFEN)"


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
    elif (
        _classify_special_tax_label(document) is None
        and not any(marker in str(document.get("taxText") or "").upper() for marker in _FOREIGN_MARKERS)
        and (
            any(position.get(key) not in (None, "") for key in (
                "taxRate", "taxRatePercent", "taxRatePercentage", "taxPercent", "taxPercentage",
            ))
            or (
                isinstance(position.get("tax"), dict)
                and any(position["tax"].get(key) not in (None, "") for key in ("rate", "percentage"))
            )
        )
    ):
        merged["taxText"] = f"MIT {_extract_position_rate(position)}% MEHRWERTSTEUER"
    label = _normalize_tax_label(merged, net_amount=net_amount, vat_amount=vat_amount)
    return label


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
