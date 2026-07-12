"""EU-OSS quarter calculation and XML export."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from threading import RLock
from typing import Any, Mapping, NamedTuple, Protocol
from xml.etree import ElementTree as ET

from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.shipping.countries import country_iso2, country_name_en

from xw_studio.services.finanzonline.oss_models import OssLine, OssQuarterResult, OssXmlExport
from xw_studio.services.finanzonline.oss_tax_rules import (
    OssTaxRule,
    known_oss_rates_by_country,
    load_oss_tax_rules,
    normalize_tax_rule_label,
)

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
    "ESTNISCHE",
    "IRISCHE",
    "PORTUGIESISCHE",
    "POLNISCHE",
    "RUMÄNISCHE",
    "RUMAENISCHE",
    "UNGARISCHE",
    "SLOWAKISCHE",
    "GRIECHISCHE",
    "KROATISCHE",
    "MALTESISCHE",
    "ZYPRIOTISCHE",
    "IVA",
    "TVA",
    "MOMS",
    "BTW",
    "PVM",
    "DPH",
    "DDV",
    "ALV",
)
_EXPORT_TAX_RULES = {"2"}
_ICS_TAX_RULES = {"3"}
_REVERSE_TAX_RULES = {"5", "21"}
_EXPORT_TAXSETS = {"45412"}
_ICS_TAXSETS = {"27267"}
_REVERSE_TAXSETS = {"35315"}
_EU_COUNTRY_CODES = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}
_DELIVERY_DATE_KEYS = ("deliveryDate", "serviceDate", "performanceDate", "invoiceDate", "date")
_CREDIT_DATE_KEYS = ("creditNoteDate", "deliveryDate", "serviceDate", "invoiceDate", "date")
_COUNTRY_KEYS = (
    "deliveryAddressCountryCode",
    "addressCountryCode",
    "deliveryCountryCode",
    "countryCode",
    "deliveryAddressCountry",
    "addressCountry",
    "country",
)
_TAX_TEXT_COUNTRY_CODES = {
    "DEUTSCHE": "DE",
    "FRANZÖSISCHE": "FR",
    "FRANZOESISCHE": "FR",
    "ITALIENISCHE": "IT",
    "NIEDERLÄNDISCHE": "NL",
    "NIEDERLAENDISCHE": "NL",
    "SPANISCHE": "ES",
    "BELGISCHE": "BE",
    "DÄNISCHE": "DK",
    "DAENISCHE": "DK",
    "FINNISCHE": "FI",
    "SCHWEDISCHE": "SE",
    "LUXEMBURGISCHE": "LU",
    "LITAUISCHE": "LT",
    "SLOWENISCHE": "SI",
    "TSCHECHISCHE": "CZ",
    "ESTNISCHE": "EE",
    "IRISCHE": "IE",
    "PORTUGIESISCHE": "PT",
    "POLNISCHE": "PL",
    "RUMÄNISCHE": "RO",
    "RUMAENISCHE": "RO",
    "UNGARISCHE": "HU",
    "SLOWAKISCHE": "SK",
    "GRIECHISCHE": "GR",
    "KROATISCHE": "HR",
    "MALTESISCHE": "MT",
    "ZYPRIOTISCHE": "CY",
}


class _RuleDecision(NamedTuple):
    oss_candidate: bool
    excluded: bool
    rate: Decimal | None
    country_code: str
    label: str
    source: str
    warning: str


class OssDocumentProvider(Protocol):
    """Source for quarter-based outbound documents."""

    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, Any]]:
        ...


class SevdeskOssDocumentProvider:
    """Best-effort sevDesk provider for EU-OSS quarter calculation."""

    def __init__(
        self,
        connection: SevdeskConnection,
        *,
        page_size: int = 1000,
        max_pages: int = 100,
        invoice_lookback_days: int = 45,
        invoice_lookahead_days: int = 10,
        max_position_workers: int = 6,
    ) -> None:
        self._connection = connection
        self._page_size = page_size
        self._max_pages = max_pages
        self._invoice_lookback_days = invoice_lookback_days
        self._invoice_lookahead_days = invoice_lookahead_days
        self._max_position_workers = max(1, int(max_position_workers))
        self._position_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._position_cache_lock = RLock()

    def load_sales_documents(self, year: int, quarter: int) -> list[dict[str, Any]]:
        start_date, end_date = _quarter_bounds(year, quarter)
        fetch_start = int(datetime.combine(start_date - timedelta(days=self._invoice_lookback_days), datetime.min.time()).timestamp())
        fetch_end = int(datetime.combine(end_date + timedelta(days=self._invoice_lookahead_days), datetime.max.time()).timestamp())
        invoices = self._load_resource(
            "/Invoice",
            params={"startDate": fetch_start, "endDate": fetch_end, "showAll": "true"},
        )
        credits = self._load_resource(
            "/CreditNote",
            params={"startDate": fetch_start, "endDate": fetch_end, "showAll": "true"},
        )

        documents: list[dict[str, Any]] = []
        for resource, rows in (("Invoice", invoices), ("CreditNote", credits)):
            for row in rows:
                prepared = dict(row)
                prepared["xw_doc_type"] = "credit" if resource == "CreditNote" else "invoice"
                prepared["xw_resource"] = resource
                documents.append(prepared)
        self._attach_positions(documents)
        return documents

    def _attach_positions(self, documents: list[dict[str, Any]]) -> None:
        jobs: list[tuple[int, str, str]] = []
        for index, document in enumerate(documents):
            resource = str(document.get("xw_resource") or "")
            doc_id = str(document.get("id") or "").strip()
            if doc_id and resource:
                jobs.append((index, resource, doc_id))
        if not jobs:
            return
        if self._max_position_workers <= 1 or len(jobs) == 1:
            for index, resource, doc_id in jobs:
                documents[index]["xw_positions"] = self._load_positions(resource, doc_id)
            return
        worker_count = min(self._max_position_workers, len(jobs))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="oss-pos") as executor:
            futures = {
                executor.submit(self._load_positions, resource, doc_id): index
                for index, resource, doc_id in jobs
            }
            for future in as_completed(futures):
                documents[futures[future]]["xw_positions"] = future.result()

    def _load_resource(self, path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        page_count = 0
        while page_count < self._max_pages:
            query = {"limit": self._page_size, "offset": offset}
            if params:
                query.update(params)
            payload = self._connection.get(path, params=query).json()
            objects = payload.get("objects") if isinstance(payload, dict) else None
            if not isinstance(objects, list) or not objects:
                break
            result.extend(item for item in objects if isinstance(item, dict))
            page_count += 1
            if len(objects) < self._page_size:
                break
            offset += self._page_size
        return result

    def _load_positions(self, resource: str, doc_id: str) -> list[dict[str, Any]]:
        cache_key = (resource, doc_id)
        with self._position_cache_lock:
            cached = self._position_cache.get(cache_key)
        if cached is not None:
            return cached
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
            objects = payload.get("objects") if isinstance(payload, dict) else None
            positions = [item for item in objects if isinstance(item, dict)] if isinstance(objects, list) else []
        except Exception as exc:
            logger.debug("OSS positions failed for %s/%s: %s", resource, doc_id, exc)
            positions = []
        with self._position_cache_lock:
            self._position_cache[cache_key] = positions
        return positions


class OssService:
    """Calculate quarter-based EU-OSS results and XML exports."""

    def __init__(
        self,
        provider: OssDocumentProvider | None = None,
        *,
        tax_rules: dict[str, OssTaxRule] | None = None,
    ) -> None:
        self._provider = provider
        self._tax_rules = tax_rules if tax_rules is not None else load_oss_tax_rules()
        self._known_rates_by_country = known_oss_rates_by_country(self._tax_rules)

    def describe_capabilities(self) -> str:
        source = "aktiv" if self._provider is not None else "nicht aktiv"
        return (
            "EU-OSS: Quartalsberechnung fuer EU-B2C-Auslandsumsatz, Preview und XML-Export.\n"
            f"Datenquelle: {source}\n"
            "Abgrenzung: kein FinanzOnline-SOAP-Upload; XML ist fuer das EU-OSS-Portal gedacht.\n"
            "Selektion: primaer deliveryDate/Leistungsdatum, dann invoiceDate; Reverse-Charge, ig Lieferung, Export und AT-Umsaetze werden ausgeschlossen."
        )

    def calculate_quarter(self, year: int, quarter: int) -> OssQuarterResult:
        if self._provider is None:
            return OssQuarterResult(
                year=year,
                quarter=quarter,
                warnings=["Keine EU-OSS-Datenquelle konfiguriert."],
            )

        documents = self._provider.load_sales_documents(year, quarter)
        start_date, end_date = _quarter_bounds(year, quarter)
        buckets: dict[tuple[str, str, bool], dict[str, Any]] = defaultdict(
            lambda: {
                "country_name": "",
                "taxable_amount": Decimal("0.00"),
                "tax_amount": Decimal("0.00"),
                "source_docs": [],
            }
        )
        warnings: list[str] = []
        source_count = 0
        excluded_count = 0

        for document in documents:
            source_count += 1
            doc_type = str(document.get("xw_doc_type") or "invoice")
            doc_label = _doc_label(document)
            doc_date = _document_date(document, doc_type)
            if doc_date is None:
                warnings.append(f"EU-OSS ohne Leistungsdatum/Belegdatum nicht uebernommen: {doc_label}")
                excluded_count += 1
                continue
            if doc_date < start_date or doc_date > end_date:
                excluded_count += 1
                continue

            exclusion = _special_exclusion(document)
            if exclusion is not None:
                excluded_count += 1
                continue
            items = _document_items(
                document,
                tax_rules=self._tax_rules,
                known_rates_by_country=self._known_rates_by_country,
            )
            if not items:
                warnings.append(f"EU-OSS ohne belastbare Positions-/Steuerdaten nicht uebernommen: {doc_label}")
                excluded_count += 1
                continue

            candidate_items = [
                item
                for item in items
                if item["net"] != Decimal("0.00") or item["vat"] != Decimal("0.00")
                if not item["excluded"] and item["oss_candidate"]
            ]
            if not candidate_items:
                for warning in _item_warnings(items, doc_label):
                    warnings.append(warning)
                excluded_count += 1
                continue

            country_code = _document_country_code(document, candidate_items)
            if not country_code:
                warnings.append(f"EU-OSS Land unklar, bitte pruefen: {doc_label}")
                excluded_count += 1
                continue
            if country_code not in _EU_COUNTRY_CODES or country_code == "AT":
                excluded_count += 1
                continue

            goods = _document_goods_flag(document)
            sign = Decimal("-1.00") if doc_type == "credit" else Decimal("1.00")
            grouped = False

            for item in items:
                for warning in _item_warnings([item], doc_label):
                    warnings.append(warning)
                if item["net"] == Decimal("0.00") and item["vat"] == Decimal("0.00"):
                    continue
                if item["excluded"]:
                    continue
                rate = item["rate"]
                if rate is None:
                    warnings.append(f"EU-OSS Steuersatz unklar, bitte pruefen: {doc_label}")
                    continue
                if not item["oss_candidate"]:
                    continue
                key = (country_code, _fmt(rate), goods)
                bucket = buckets[key]
                bucket["country_name"] = country_name_en(country_code)
                bucket["taxable_amount"] += item["net"] * sign
                bucket["tax_amount"] += item["vat"] * sign
                bucket["source_docs"].append(doc_label)
                grouped = True

            if not grouped:
                excluded_count += 1

            if doc_type == "credit" and _has_credit_reference(document):
                warnings.append(
                    f"Gutschrift im OSS-Quartal erkannt, Korrektur im Portal pruefen: {doc_label}"
                )

        goods_lines: list[OssLine] = []
        service_lines: list[OssLine] = []
        for (country_code, vat_rate, goods), bucket in sorted(buckets.items()):
            line = OssLine(
                country_code=country_code,
                country_name=str(bucket["country_name"] or country_name_en(country_code)),
                vat_rate=vat_rate,
                taxable_amount=_fmt(bucket["taxable_amount"]),
                tax_amount=_fmt(bucket["tax_amount"]),
                goods=goods,
                source_docs=_dedupe_strings(bucket["source_docs"]),
            )
            if goods:
                goods_lines.append(line)
            else:
                service_lines.append(line)

        if not goods_lines and not service_lines:
            warnings.append("Nullquartal: EU-OSS im Portal als Nullmeldung pruefen/einreichen.")

        return OssQuarterResult(
            year=year,
            quarter=quarter,
            goods_lines=goods_lines,
            service_lines=service_lines,
            warnings=_dedupe_strings(warnings),
            source_count=source_count,
            excluded_count=excluded_count,
        )

    def render_preview_text(self, result: OssQuarterResult) -> str:
        lines = [
            f"EU-OSS Quartal Q{result.quarter}/{result.year}",
            f"Gepruefte Belege: {result.source_count}",
            f"Ausgeschlossene Belege: {result.excluded_count}",
        ]
        for title, entries in (("Waren", result.goods_lines), ("Leistungen", result.service_lines)):
            lines.extend(["", title])
            if not entries:
                lines.append("- keine")
                continue
            for row in entries:
                lines.append(
                    f"- {row.country_code} {row.country_name}: Netto EUR {_euro(row.taxable_amount)}, USt EUR {_euro(row.tax_amount)}, Satz {row.vat_rate}%, Typ {'Waren' if row.goods else 'Leistungen'}"
                )
        if result.warnings:
            lines.extend(["", "Hinweise:"])
            lines.extend(f"- {warning}" for warning in result.warnings)
        return "\n".join(lines).strip()

    def build_xml_export(
        self,
        year: int,
        quarter: int,
        *,
        oss_id: str,
        uid_fixed_est: str = "",
    ) -> OssXmlExport:
        result = self.calculate_quarter(year, quarter)
        if not result.goods_lines and not result.service_lines:
            raise ValueError("Kein EU-OSS-Umsatz im Quartal. Nullmeldung bitte direkt im Portal einreichen.")
        xml_payload = build_oss_xml(result, oss_id=oss_id, uid_fixed_est=uid_fixed_est)
        validate_oss_xml(xml_payload)
        return OssXmlExport(
            year=year,
            quarter=quarter,
            file_name=f"EU-OSS_{year}_Q{quarter}.xml",
            xml_payload=xml_payload,
            line_count=len(result.goods_lines) + len(result.service_lines),
            warnings=list(result.warnings),
        )

    @staticmethod
    def portal_url(*, test_mode: bool = True) -> str:
        if test_mode:
            return "https://fon-moss.bmf.gv.at/extern/moss/test_fileupload_oss"
        return "https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/Umsatzsteuer-One-Stop-Shop/EU-OSS/Erklaerung-und-Zahlung-im-EU-OSS.html"


def build_oss_xml(result: OssQuarterResult, *, oss_id: str, uid_fixed_est: str = "") -> str:
    clean_oss_id = str(oss_id or "").strip()
    if not clean_oss_id:
        raise ValueError("OSS-ID darf nicht leer sein.")
    root = ET.Element("OSSReturn")
    ET.SubElement(root, "ossId").text = clean_oss_id
    ET.SubElement(root, "year").text = str(result.year)
    ET.SubElement(root, "quarter").text = str(result.quarter)

    for line in [*result.goods_lines, *result.service_lines]:
        mscon = ET.SubElement(root, "mscon")
        ET.SubElement(mscon, "countryCode").text = line.country_code
        ET.SubElement(mscon, "goods").text = "true" if line.goods else "false"
        ET.SubElement(mscon, "taxable").text = _comma_amount(line.taxable_amount)
        ET.SubElement(mscon, "vatRate").text = _comma_amount(line.vat_rate)
        ET.SubElement(mscon, "taxAmount").text = _comma_amount(line.tax_amount)
        if uid_fixed_est.strip():
            ET.SubElement(mscon, "uidFixedEst").text = uid_fixed_est.strip()

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def validate_oss_xml(xml_payload: str) -> None:
    xml_doc = ET.fromstring(xml_payload.encode("utf-8"))
    if xml_doc.tag != "OSSReturn":
        raise ValueError("OSS-XML hat kein OSSReturn-Wurzelelement.")
    required = {"ossId", "year", "quarter"}
    present = {child.tag for child in xml_doc}
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"OSS-XML unvollstaendig: {', '.join(missing)}")


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    if quarter not in {1, 2, 3, 4}:
        raise ValueError("quarter muss zwischen 1 und 4 liegen")
    start_month = (quarter - 1) * 3 + 1
    start_date = date(year, start_month, 1)
    if quarter == 4:
        end_date = date(year, 12, 31)
    else:
        next_start = date(year, start_month + 3, 1)
        end_date = next_start - timedelta(days=1)
    return start_date, end_date


def _document_items(
    document: dict[str, Any],
    *,
    tax_rules: Mapping[str, OssTaxRule],
    known_rates_by_country: Mapping[str, frozenset[Decimal]],
) -> list[dict[str, Any]]:
    positions = document.get("xw_positions")
    items: list[dict[str, Any]] = []
    if isinstance(positions, list) and positions:
        for position in positions:
            if not isinstance(position, dict):
                continue
            net, vat = _extract_position_amounts(position)
            tax_text = position.get("taxText") or document.get("taxText")
            items.append(_build_item(
                document,
                tax_text,
                net,
                vat,
                position,
                tax_rules=tax_rules,
                known_rates_by_country=known_rates_by_country,
                source="position",
                fallback_reason="",
            ))
        header_item = _document_header_item(
            document,
            tax_rules=tax_rules,
            known_rates_by_country=known_rates_by_country,
            fallback_reason="",
        )
        fallback_reason = _document_fallback_reason(items, header_item)
        if fallback_reason:
            return [
                _document_header_item(
                    document,
                    tax_rules=tax_rules,
                    known_rates_by_country=known_rates_by_country,
                    fallback_reason=fallback_reason,
                )
            ]
        if items:
            return items

    return [
        _document_header_item(
            document,
            tax_rules=tax_rules,
            known_rates_by_country=known_rates_by_country,
            fallback_reason="",
        )
    ]


def _document_header_item(
    document: dict[str, Any],
    *,
    tax_rules: Mapping[str, OssTaxRule],
    known_rates_by_country: Mapping[str, frozenset[Decimal]],
    fallback_reason: str,
) -> dict[str, Any]:
    net = _first_decimal(document, "sumNet", "sumNetAccounting")
    vat = _first_decimal(document, "sumTax", "sumTaxAccounting")
    tax_text = document.get("taxText")
    return _build_item(
        document,
        tax_text,
        net,
        vat,
        document,
        tax_rules=tax_rules,
        known_rates_by_country=known_rates_by_country,
        source="document",
        fallback_reason=fallback_reason,
    )


def _build_item(
    document: dict[str, Any],
    tax_text: object,
    net: Decimal,
    vat: Decimal,
    payload: dict[str, Any],
    *,
    tax_rules: Mapping[str, OssTaxRule],
    known_rates_by_country: Mapping[str, frozenset[Decimal]],
    source: str,
    fallback_reason: str,
) -> dict[str, Any]:
    decision = _classify_tax_rule(
        document,
        tax_text,
        net,
        vat,
        payload,
        tax_rules=tax_rules,
        known_rates_by_country=known_rates_by_country,
    )
    return {
        "net": net,
        "vat": vat,
        "tax_text": str(tax_text or ""),
        "rate": decision.rate,
        "oss_candidate": decision.oss_candidate,
        "excluded": decision.excluded,
        "country_code": decision.country_code,
        "rule_label": decision.label,
        "classification_source": decision.source,
        "warning": decision.warning,
        "fallback_reason": fallback_reason,
        "source": source,
    }


def _document_fallback_reason(items: list[dict[str, Any]], header_item: dict[str, Any]) -> str:
    if not header_item["oss_candidate"] or header_item["excluded"]:
        return ""
    position_candidates = [
        item for item in items
        if not item["excluded"] and item["oss_candidate"] and item["rate"] == header_item["rate"]
    ]
    if not position_candidates:
        return "Dokumentkopf genutzt, weil Positionen keine passende OSS-Regel liefern"
    position_countries = {str(item.get("country_code") or "") for item in position_candidates}
    position_rates = {item.get("rate") for item in position_candidates}
    if len(position_countries) > 1 or len(position_rates) > 1:
        return ""
    pos_net = sum((item["net"] for item in position_candidates), Decimal("0.00"))
    pos_vat = sum((item["vat"] for item in position_candidates), Decimal("0.00"))
    if abs(pos_net - header_item["net"]) > _DECIMAL_2 or abs(pos_vat - header_item["vat"]) > _DECIMAL_2:
        return "Dokumentkopf genutzt, weil Positionssumme nicht zum Belegkopf passt"
    return ""


def _item_warnings(items: list[dict[str, Any]], doc_label: str) -> list[str]:
    warnings: list[str] = []
    for item in items:
        warning = str(item.get("warning") or "").strip()
        if warning:
            warnings.append(f"{warning}: {doc_label}")
        fallback_reason = str(item.get("fallback_reason") or "").strip()
        if fallback_reason:
            warnings.append(f"EU-OSS {fallback_reason}: {doc_label}")
    return warnings


def _classify_tax_rule(
    document: dict[str, Any],
    tax_text: object,
    net_amount: Decimal,
    vat_amount: Decimal,
    rate_source: dict[str, Any],
    *,
    tax_rules: Mapping[str, OssTaxRule],
    known_rates_by_country: Mapping[str, frozenset[Decimal]],
) -> _RuleDecision:
    raw_text = str(tax_text or "").strip()
    normalized = normalize_tax_rule_label(raw_text)
    rule = tax_rules.get(normalized) if normalized else None
    if _position_excluded(document, tax_text):
        return _RuleDecision(False, True, None, "", raw_text, "text_exclusion", "")
    if rule is not None:
        if not rule.oss_eligible:
            return _RuleDecision(False, True, rule.vat_rate, rule.country_code, rule.label, "tax_rule", "")
        if rule.vat_rate == Decimal("0.00") and vat_amount != Decimal("0.00"):
            return _RuleDecision(
                False,
                False,
                rule.vat_rate,
                rule.country_code,
                rule.label,
                "tax_rule",
                f"EU-OSS Datenkonflikt: {rule.label} hat 0 %, aber Steuerbetrag {_fmt(vat_amount)} EUR",
            )
        return _RuleDecision(True, False, rule.vat_rate, rule.country_code, rule.label, "tax_rule", "")

    rate = _resolve_rate(tax_text, net_amount, vat_amount, rate_source)
    country_code = _document_country_code(document)
    if not raw_text or raw_text == "0":
        if country_code and country_code in known_rates_by_country and rate in known_rates_by_country[country_code]:
            return _RuleDecision(
                True,
                False,
                rate,
                country_code,
                raw_text,
                "country_rate_fallback",
                "EU-OSS USt-Regel aus Land/Satz abgeleitet, sevDesk-Regeltext fehlt",
            )
        return _RuleDecision(False, False, rate, country_code, raw_text, "missing_tax_rule", "")
    if any(marker in normalized for marker in _FOREIGN_MARKERS):
        return _RuleDecision(
            False,
            False,
            rate,
            country_code,
            raw_text,
            "unknown_foreign_tax_rule",
            f"EU-OSS unbekannte sevDesk-USt-Regel '{raw_text}', TaxSet/Regel in sevDesk pruefen",
        )
    if country_code and country_code in _EU_COUNTRY_CODES and country_code != "AT" and rate in known_rates_by_country.get(country_code, frozenset()):
        return _RuleDecision(
            True,
            False,
            rate,
            country_code,
            raw_text,
            "country_rate_fallback",
            "EU-OSS USt-Regel aus Land/Satz abgeleitet, sevDesk-Regeltext nicht in OSS-Matrix",
        )
    return _RuleDecision(False, False, rate, country_code, raw_text, "not_oss", "")


def _extract_position_amounts(position: dict[str, Any]) -> tuple[Decimal, Decimal]:
    net_amount = _first_decimal(
        position,
        "sumNetAccounting",
        "sumNet",
        "amountNet",
        "priceNet",
        "priceNetAccounting",
        "net",
    )
    vat_amount = _first_decimal(position, "sumTaxAccounting", "sumTax")
    if net_amount == Decimal("0.00"):
        quantity = _to_decimal(position.get("quantity") or 1)
        price = _to_decimal(position.get("price") or 0)
        net_amount = (quantity * price).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    if vat_amount == Decimal("0.00") and net_amount != Decimal("0.00"):
        rate = _extract_position_rate(position)
        if rate > Decimal("0.00"):
            vat_amount = (net_amount * rate / Decimal("100")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    return net_amount, vat_amount


def _document_date(document: dict[str, Any], doc_type: str) -> date | None:
    keys = _CREDIT_DATE_KEYS if doc_type == "credit" else _DELIVERY_DATE_KEYS
    for key in keys:
        parsed = _parse_date(document.get(key))
        if parsed is not None:
            return parsed.date()
    return None


def _document_country_code(document: dict[str, Any], items: list[dict[str, Any]] | None = None) -> str:
    if items:
        for item in items:
            code = str(item.get("country_code") or "").strip().upper()
            if code:
                return code
    for key in _COUNTRY_KEYS:
        value = document.get(key)
        code = country_iso2(value)
        if code:
            return code
    for key in ("deliveryAddress", "address", "contact", "shippingAddress"):
        code = country_iso2(document.get(key))
        if code:
            return code
    tax_texts = [str(document.get("taxText") or "")]
    if items:
        tax_texts.extend(str(item.get("tax_text") or "") for item in items)
    for tax_text in tax_texts:
        code = _country_code_from_tax_text(tax_text)
        if code:
            return code
    return ""


def _country_code_from_tax_text(value: str) -> str:
    upper = str(value or "").upper()
    for marker, code in _TAX_TEXT_COUNTRY_CODES.items():
        if marker in upper:
            return code
    return ""


def _document_goods_flag(document: dict[str, Any]) -> bool:
    explicit = document.get("xw_oss_goods")
    if isinstance(explicit, bool):
        return explicit
    if isinstance(explicit, str):
        return explicit.strip().lower() not in {"0", "false", "no", "nein"}
    goods = document.get("goods")
    if isinstance(goods, bool):
        return goods
    return True


def _special_exclusion(document: dict[str, Any]) -> str | None:
    tax_rule = _reference_id(document.get("taxRule"))
    tax_set = _reference_id(document.get("taxSet"))
    tax_type = str(document.get("taxType") or "").strip().lower()
    tax_text = str(document.get("taxText") or "").upper()
    if tax_rule in _EXPORT_TAX_RULES or tax_set in _EXPORT_TAXSETS or "AUSFUHR" in tax_text:
        return "export"
    if tax_rule in _REVERSE_TAX_RULES or tax_set in _REVERSE_TAXSETS or ("REVERSE" in tax_text and "CHARGE" in tax_text):
        return "reverse_charge"
    if tax_rule in _ICS_TAX_RULES or tax_type == "eu" or tax_set in _ICS_TAXSETS or (
        "INNERGEMEINSCHAFT" in tax_text and "LIEFER" in tax_text
    ):
        return "ics"
    return None


def _position_excluded(document: dict[str, Any], tax_text: object) -> bool:
    upper = str(tax_text or document.get("taxText") or "").upper()
    return (
        ("REVERSE" in upper and "CHARGE" in upper)
        or ("INNERGEMEINSCHAFT" in upper and "LIEFER" in upper)
        or ("AUSFUHR" in upper)
    )


def _resolve_rate(
    tax_text: object,
    net_amount: Decimal,
    vat_amount: Decimal,
    payload: dict[str, Any],
) -> Decimal | None:
    match = _PERCENT_RE.search(str(tax_text or ""))
    if match is not None:
        try:
            return Decimal(match.group(1).replace(",", ".")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None
    rate = _extract_position_rate(payload)
    if rate > Decimal("0.00"):
        return rate.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    if net_amount != Decimal("0.00") and vat_amount != Decimal("0.00"):
        return ((vat_amount / net_amount) * Decimal("100")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    return None


def _extract_position_rate(payload: dict[str, Any]) -> Decimal:
    for key in ("taxRate", "taxRatePercent", "taxRatePercentage", "taxPercent", "taxPercentage"):
        value = payload.get(key)
        if value not in (None, ""):
            return _to_decimal(value)
    tax_node = payload.get("tax")
    if isinstance(tax_node, dict):
        for key in ("rate", "percentage"):
            value = tax_node.get(key)
            if value not in (None, ""):
                return _to_decimal(value)
    return Decimal("0.00")


def _reference_id(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("value") or "").strip()
    return str(value or "").strip()


def _has_credit_reference(document: dict[str, Any]) -> bool:
    for key in ("refSrcInvoice", "refSrcInvoiceId", "refInvoice", "refInvoiceId", "invoiceId"):
        if _reference_id(document.get(key)):
            return True
    return False


def _doc_label(document: dict[str, Any]) -> str:
    for key in ("invoiceNumber", "creditNoteNumber", "number", "reference", "id"):
        value = document.get(key)
        if value not in (None, ""):
            return str(value)
    return "unbekannt"


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


def _euro(value: str) -> str:
    amount = _to_decimal(value)
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


def _comma_amount(value: str) -> str:
    return _fmt(_to_decimal(value)).replace(".", ",")


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
