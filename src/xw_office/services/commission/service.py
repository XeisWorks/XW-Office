"""Commission calculations with sevDesk-backed document aggregation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from xw_office.services.http_client import SevdeskConnection
from xw_office.services.products.catalog import normalize_legacy_title
from xw_office.services.sevdesk.part_client import PartClient
from xw_office.services.sevdesk.invoice_client import extract_wix_order_number

if TYPE_CHECKING:
    from xw_office.services.products.catalog import ProductCatalogService
    from xw_office.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 5_000
_MAX_PAGES = 100
_CANCEL_INVOICE_TYPES = {"SR"}


@dataclass(frozen=True)
class CommissionProfile:
    """Configuration of one commission analysis profile."""

    key: str
    label: str
    category_names: tuple[str, ...]
    commission_rate_percent: float = 0.0
    include_credit_notes: bool = True
    include_cancellation_invoices: bool = True
    date_policy: str = "invoice_date"
    sku_patterns: tuple[str, ...] = ()
    resolve_unreleased_titles: bool = False


@dataclass(frozen=True)
class CommissionPeriod:
    """Time period and basis used for one commission run."""

    start: date
    end: date
    basis: str
    reference_date: date


@dataclass
class DocumentContribution:
    """One signed row contribution from invoice/credit-note position."""

    document_id: str
    document_number: str
    document_type: str
    document_date: str
    source_kind: str
    sku: str
    name: str
    category_name: str
    raw_quantity: float
    raw_net: float
    raw_gross: float
    signed_quantity: float
    signed_net: float
    signed_gross: float
    rule: str
    warning: str = ""


@dataclass
class ProductBreakdownRow:
    """Aggregated values per SKU."""

    sku: str
    name: str
    sold_quantity: float = 0.0
    canceled_quantity: float = 0.0
    credited_quantity: float = 0.0
    net_quantity: float = 0.0
    net_amount: float = 0.0
    gross_amount: float = 0.0
    category_names: tuple[str, ...] = ()
    warning: str = ""


@dataclass
class CategoryBreakdownRow:
    """Aggregated values per category."""

    category_name: str
    quantity: float = 0.0
    net_amount: float = 0.0
    gross_amount: float = 0.0
    share_of_net_amount: float = 0.0


@dataclass
class CommissionSummary:
    """High-level KPI values for one run."""

    total_net_quantity: float = 0.0
    total_net_amount: float = 0.0
    total_gross_amount: float = 0.0
    total_correction_quantity: float = 0.0
    document_count: int = 0
    anomaly_count: int = 0


@dataclass(frozen=True)
class UnreleasedResolutionIssue:
    """A title/owner decision that must be confirmed in the UI."""

    raw_title: str
    document_number: str
    order_reference: str
    sku: str
    reason: str
    quantity: int = 1
    needs_title_split: bool = False


@dataclass
class CommissionRunResult:
    """Full result bundle consumed by UI and exports."""

    profile: CommissionProfile
    period: CommissionPeriod
    summary: CommissionSummary
    product_rows: list[ProductBreakdownRow]
    category_rows: list[CategoryBreakdownRow]
    document_rows: list[DocumentContribution]
    anomalies: list[str]
    source_stats: dict[str, int]
    unresolved_titles: list[UnreleasedResolutionIssue] | None = None


def format_commission_summary(result: CommissionRunResult) -> str:
    """Render a compact, human-readable commission statement for the clipboard."""
    categories = result.profile.category_names
    if result.profile.resolve_unreleased_titles:
        sku_filter = (
            f"Filter: SKU {', '.join(result.profile.sku_patterns)}; Zuordnung über Titel-Aliase"
        )
    elif len(categories) == 1:
        sku_filter = f"Filter: sevDesk-Kategorie {categories[0]}"
    else:
        sku_filter = f"Filter: sevDesk-Kategorien {', '.join(categories)}"
    basis_label = {
        "invoice_date": "Rechnungsdatum",
        "payment_date": "Zahlungsdatum",
    }.get(result.period.basis, result.period.basis)

    lines = [
        f"Kategorie: {result.profile.label}",
        (
            f"Zeitraum: {result.period.start.strftime('%d.%m.%Y')} - "
            f"{result.period.end.strftime('%d.%m.%Y')}"
        ),
        f"Basisdatum: {basis_label}",
        f"SKU-Filter: {sku_filter}",
        f"Gesamtmenge: {_format_de_number(result.summary.total_net_quantity, trim=True)}",
        f"Netto gesamt: {_format_de_number(result.summary.total_net_amount)} EUR",
        "",
        "Produkte:",
        "SKU\tName\tMenge\tNetto",
        "",
    ]
    lines.extend(
        (
            f"{row.sku}\t{row.name}\t{_format_de_number(row.net_quantity, trim=True)} Stk.\t"
            f"{_format_de_number(row.net_amount)} EUR netto"
        )
        for row in result.product_rows
    )

    rate = result.profile.commission_rate_percent
    if rate > 0:
        invoice_amount = calculate_commission_amount(result.summary.total_net_amount, rate)
        lines.extend(
            [
                "",
                f"Rechnungsbetrag ({_format_de_number(rate, trim=True)}%): "
                f"€ {_format_de_number(invoice_amount)}",
            ]
        )
    return "\n".join(lines)


def calculate_commission_amount(net_amount: float, rate_percent: float) -> float:
    """Calculate a currency amount using commercial cent rounding."""
    amount = Decimal(str(net_amount)) * Decimal(str(rate_percent)) / Decimal("100")
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class CommissionDataProvider(Protocol):
    """Abstract data source used by commission calculations."""

    def list_part_categories(self) -> list[dict[str, str]]: ...

    def list_parts(self) -> list[dict[str, Any]]: ...

    def list_invoices_for_year(self, year: int) -> list[dict[str, Any]]: ...

    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, Any]]: ...

    def list_invoice_positions_bulk(self, invoice_ids: list[str]) -> list[dict[str, Any]]: ...

    def list_credit_notes_for_year(self, year: int) -> list[dict[str, Any]]: ...

    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, Any]]: ...

    def list_credit_note_positions_bulk(
        self, credit_note_ids: list[str]
    ) -> list[dict[str, Any]]: ...


class SevdeskCommissionProvider:
    """Read-only bulk provider for invoices, credit notes, and article metadata."""

    def __init__(
        self,
        connection: SevdeskConnection,
        part_client: PartClient,
        *,
        page_size: int = _PAGE_SIZE,
        max_pages: int = _MAX_PAGES,
    ) -> None:
        self._connection = connection
        self._part_client = part_client
        self._page_size = page_size
        self._max_pages = max_pages
        self._invoice_cache: dict[int, list[dict[str, Any]]] = {}
        self._credit_cache: dict[int, list[dict[str, Any]]] = {}
        self._invoice_pos_cache: dict[str, list[dict[str, Any]]] = {}
        self._credit_pos_cache: dict[str, list[dict[str, Any]]] = {}
        self._bulk_position_resources_loaded: set[str] = set()
        self._parts_cache: list[dict[str, Any]] | None = None
        self._categories_cache: list[dict[str, str]] | None = None

    def clear_cache(self) -> None:
        self._invoice_cache.clear()
        self._credit_cache.clear()
        self._invoice_pos_cache.clear()
        self._credit_pos_cache.clear()
        self._bulk_position_resources_loaded.clear()
        self._parts_cache = None
        self._categories_cache = None

    def list_part_categories(self) -> list[dict[str, str]]:
        if self._categories_cache is None:
            self._categories_cache = self._part_client.list_part_categories()
        return [dict(item) for item in self._categories_cache]

    def list_parts(self) -> list[dict[str, Any]]:
        if self._parts_cache is None:
            self._parts_cache = [
                row.model_dump() for row in self._part_client.list_parts(refresh_cache=True)
            ]
        return [dict(item) for item in self._parts_cache]

    def list_invoices_for_year(self, year: int) -> list[dict[str, Any]]:
        if year not in self._invoice_cache:
            start_ts, end_ts = _year_bounds_timestamps(year)
            self._invoice_cache[year] = self._load_resource(
                "/Invoice",
                params={"startDate": start_ts, "endDate": end_ts, "showAll": "true"},
            )
        return [dict(item) for item in self._invoice_cache[year]]

    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, Any]]:
        doc_id = str(invoice_id).strip()
        if not doc_id:
            return []
        if doc_id not in self._invoice_pos_cache:
            payload = self._connection.get(
                "/InvoicePos",
                params={
                    "invoice[id]": doc_id,
                    "invoice[objectName]": "Invoice",
                    "embed": "part",
                },
            ).json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            self._invoice_pos_cache[doc_id] = [
                dict(item)
                for item in objects
                if isinstance(objects, list) and isinstance(item, dict)
            ]
        return [dict(item) for item in self._invoice_pos_cache[doc_id]]

    def list_invoice_positions_bulk(self, invoice_ids: list[str]) -> list[dict[str, Any]]:
        return self._load_positions_bulk(
            "/InvoicePos",
            parent_key="invoice",
            document_ids=invoice_ids,
            cache=self._invoice_pos_cache,
        )

    def list_credit_notes_for_year(self, year: int) -> list[dict[str, Any]]:
        if year not in self._credit_cache:
            start_ts, end_ts = _year_bounds_timestamps(year)
            self._credit_cache[year] = self._load_resource(
                "/CreditNote",
                params={"startDate": start_ts, "endDate": end_ts, "showAll": "true"},
            )
        return [dict(item) for item in self._credit_cache[year]]

    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, Any]]:
        doc_id = str(credit_note_id).strip()
        if not doc_id:
            return []
        if doc_id not in self._credit_pos_cache:
            payload = self._connection.get(
                "/CreditNotePos",
                params={
                    "creditNote[id]": doc_id,
                    "creditNote[objectName]": "CreditNote",
                    "embed": "part",
                },
            ).json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            self._credit_pos_cache[doc_id] = [
                dict(item)
                for item in objects
                if isinstance(objects, list) and isinstance(item, dict)
            ]
        return [dict(item) for item in self._credit_pos_cache[doc_id]]

    def list_credit_note_positions_bulk(self, credit_note_ids: list[str]) -> list[dict[str, Any]]:
        return self._load_positions_bulk(
            "/CreditNotePos",
            parent_key="creditNote",
            document_ids=credit_note_ids,
            cache=self._credit_pos_cache,
        )

    def _load_positions_bulk(
        self,
        path: str,
        *,
        parent_key: str,
        document_ids: list[str],
        cache: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(item).strip() for item in document_ids if str(item).strip()))
        if not ids:
            return []

        # sevDesk currently treats repeated or comma-separated parent filters as
        # one single ID.  Loading in chunks would therefore silently omit almost
        # every invoice.  One paginated resource snapshot is both correct and far
        # faster than one HTTP request per document; select the requested parents
        # locally and keep the snapshot grouped for subsequent runs.
        if path not in self._bulk_position_resources_loaded:
            rows = self._load_resource(path, params={"embed": "part"})
            for row in rows:
                parent_id = _reference_id(row.get(parent_key)).strip()
                if parent_id:
                    cache.setdefault(parent_id, []).append(row)
            self._bulk_position_resources_loaded.add(path)
        for item in ids:
            cache.setdefault(item, [])
        return [dict(row) for item in ids for row in cache.get(item, [])]

    def _load_resource(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        page_count = 0
        while page_count < self._max_pages:
            query: dict[str, Any] = {"limit": self._page_size, "offset": offset}
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
        if page_count >= self._max_pages and len(objects) >= self._page_size:
            raise RuntimeError(
                f"sevDesk-Datenabruf fuer {path} nach {self._max_pages} Seiten unvollstaendig. "
                "Die Abrechnung wurde sicherheitshalber abgebrochen."
            )
        return result


class CommissionService:
    """Business logic for commission runs and profile filtering."""

    def __init__(
        self,
        provider: CommissionDataProvider | None = None,
        *,
        profile_config_path: Path | None = None,
        product_catalog: ProductCatalogService | None = None,
        wix_orders: WixOrdersClient | None = None,
    ) -> None:
        self._provider = provider
        self._product_catalog = product_catalog
        self._wix_orders = wix_orders
        self._profiles = self._load_profiles(profile_config_path)

    def list_profiles(self) -> list[CommissionProfile]:
        return sorted(self._profiles.values(), key=lambda profile: profile.label.lower())

    def get_profile(self, profile_key: str) -> CommissionProfile:
        profile = self._profiles.get(profile_key)
        if profile is None:
            raise KeyError(f"Commission-Profil nicht gefunden: {profile_key}")
        return profile

    def resolve_period(
        self,
        period_key: str,
        *,
        reference_date: date | None = None,
        custom_start: date | None = None,
        custom_end: date | None = None,
        basis: str = "invoice_date",
    ) -> CommissionPeriod:
        today = reference_date or date.today()
        key = period_key.strip().lower()

        if key == "last_month":
            first_of_current = date(today.year, today.month, 1)
            end = first_of_current - timedelta(days=1)
            start = date(end.year, end.month, 1)
        elif key == "last_quarter":
            current_q = (today.month - 1) // 3 + 1
            prev_q = 4 if current_q == 1 else current_q - 1
            year = today.year - 1 if prev_q == 4 and current_q == 1 else today.year
            start_month = (prev_q - 1) * 3 + 1
            start = date(year, start_month, 1)
            end_month = start_month + 2
            end = _month_end(year, end_month)
        elif key == "last_half_year":
            if today.month <= 6:
                start = date(today.year - 1, 7, 1)
                end = date(today.year - 1, 12, 31)
            else:
                start = date(today.year, 1, 1)
                end = date(today.year, 6, 30)
        elif key == "last_year":
            year = today.year - 1
            start = date(year, 1, 1)
            end = date(year, 12, 31)
        elif key == "custom":
            if custom_start is None or custom_end is None:
                raise ValueError("custom_start und custom_end sind erforderlich")
            if custom_end < custom_start:
                raise ValueError("custom_end muss >= custom_start sein")
            start = custom_start
            end = custom_end
        else:
            raise ValueError(f"Unbekannter Zeitraum: {period_key}")

        return CommissionPeriod(start=start, end=end, basis=basis, reference_date=today)

    def run_profile(
        self,
        profile_key: str,
        period: CommissionPeriod,
        *,
        include_cancellation_invoices: bool | None = None,
        include_credit_notes: bool | None = None,
        refresh_data: bool = False,
    ) -> CommissionRunResult:
        if self._provider is None:
            raise RuntimeError("Keine Commission-Datenquelle konfiguriert.")

        profile = self.get_profile(profile_key)

        if refresh_data and hasattr(self._provider, "clear_cache"):
            try:
                getattr(self._provider, "clear_cache")()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Commission cache clear skipped: %s", exc)

        use_cancellations = (
            profile.include_cancellation_invoices
            if include_cancellation_invoices is None
            else include_cancellation_invoices
        )
        use_credit_notes = (
            profile.include_credit_notes if include_credit_notes is None else include_credit_notes
        )

        categories = self._provider.list_part_categories()
        category_name_to_id = {
            str(item.get("name") or "").strip().casefold(): str(item.get("id") or "").strip()
            for item in categories
            if str(item.get("name") or "").strip() and str(item.get("id") or "").strip()
        }
        profile_category_ids = {
            category_name_to_id[name.casefold()]
            for name in profile.category_names
            if name.casefold() in category_name_to_id
        }
        missing_category_names = [
            name for name in profile.category_names if name.casefold() not in category_name_to_id
        ]
        if missing_category_names:
            missing = ", ".join(missing_category_names)
            raise RuntimeError(
                f"Konfigurierte sevDesk-Kategorie nicht gefunden: {missing}. "
                "Die Abrechnung wurde sicherheitshalber nicht ausgefuehrt."
            )

        parts = self._provider.list_parts()
        parts_by_id = {
            str(part.get("id") or "").strip(): part
            for part in parts
            if str(part.get("id") or "").strip()
        }

        source_stats: dict[str, int] = {
            "invoices_loaded": 0,
            "invoice_positions_loaded": 0,
            "credit_notes_loaded": 0,
            "credit_positions_loaded": 0,
            "positions_included": 0,
            "positions_skipped_no_profile_match": 0,
            "positions_skipped_missing_date": 0,
            "documents_skipped_draft": 0,
            "invoices_with_discount": 0,
            "titles_unresolved": 0,
        }

        anomalies: list[str] = []
        unresolved_titles: list[UnreleasedResolutionIssue] = []
        contributions: list[DocumentContribution] = []
        years = range(period.start.year, period.end.year + 1)

        for year in years:
            invoices = self._provider.list_invoices_for_year(year)
            source_stats["invoices_loaded"] += len(invoices)
            eligible_invoices: list[tuple[str, dict[str, Any], str]] = []
            for invoice in invoices:
                if _is_draft_document(invoice):
                    source_stats["documents_skipped_draft"] += 1
                    continue
                doc_date = _pick_date(invoice, ("invoiceDate", "date", "create", "updated"))
                if doc_date is None:
                    source_stats["positions_skipped_missing_date"] += 1
                    continue
                if doc_date < period.start or doc_date > period.end:
                    continue

                invoice_type = str(invoice.get("invoiceType") or "RE").strip().upper()
                is_cancel = invoice_type in _CANCEL_INVOICE_TYPES
                if is_cancel and not use_cancellations:
                    continue

                invoice_id = str(invoice.get("id") or "").strip()
                if not invoice_id:
                    continue
                eligible_invoices.append((invoice_id, invoice, invoice_type))

            invoice_positions = self._provider.list_invoice_positions_bulk(
                [item[0] for item in eligible_invoices]
            )
            source_stats["invoice_positions_loaded"] += len(invoice_positions)
            positions_by_invoice = _group_positions_by_parent(invoice_positions, "invoice")
            for invoice_id, invoice, invoice_type in eligible_invoices:
                net_factor = _invoice_discount_factor(
                    invoice, positions_by_invoice.get(invoice_id, [])
                )
                if net_factor < 1.0:
                    source_stats["invoices_with_discount"] += 1
                document_positions = positions_by_invoice.get(invoice_id, [])
                if profile.resolve_unreleased_titles:
                    built_rows, issues = self._build_unreleased_contributions(
                        source_kind="invoice",
                        document=invoice,
                        positions=document_positions,
                        parts_by_id=parts_by_id,
                        invoice_type=invoice_type,
                        net_factor=net_factor,
                        profile=profile,
                    )
                    contributions.extend(built_rows)
                    unresolved_titles.extend(issues)
                    source_stats["positions_included"] += len(built_rows)
                    source_stats["titles_unresolved"] += len(issues)
                    continue
                for pos in document_positions:
                    built = self._build_contribution(
                        source_kind="invoice",
                        document=invoice,
                        position=pos,
                        parts_by_id=parts_by_id,
                        profile_category_ids=profile_category_ids,
                        invoice_type=invoice_type,
                        net_factor=net_factor,
                    )
                    if built is None:
                        source_stats["positions_skipped_no_profile_match"] += 1
                        continue
                    source_stats["positions_included"] += 1
                    contributions.append(built)
                    if built.warning:
                        anomalies.append(built.warning)

            if not use_credit_notes:
                continue

            credit_notes = self._provider.list_credit_notes_for_year(year)
            source_stats["credit_notes_loaded"] += len(credit_notes)
            eligible_credits: list[tuple[str, dict[str, Any]]] = []
            for credit in credit_notes:
                if _is_draft_document(credit):
                    source_stats["documents_skipped_draft"] += 1
                    continue
                doc_date = _pick_date(credit, ("creditNoteDate", "date", "create", "updated"))
                if doc_date is None:
                    source_stats["positions_skipped_missing_date"] += 1
                    continue
                if doc_date < period.start or doc_date > period.end:
                    continue

                credit_id = str(credit.get("id") or "").strip()
                if not credit_id:
                    continue
                eligible_credits.append((credit_id, credit))

            credit_positions = self._provider.list_credit_note_positions_bulk(
                [item[0] for item in eligible_credits]
            )
            source_stats["credit_positions_loaded"] += len(credit_positions)
            positions_by_credit = _group_positions_by_parent(credit_positions, "creditNote")
            for credit_id, credit in eligible_credits:
                document_positions = positions_by_credit.get(credit_id, [])
                if profile.resolve_unreleased_titles:
                    built_rows, issues = self._build_unreleased_contributions(
                        source_kind="credit_note",
                        document=credit,
                        positions=document_positions,
                        parts_by_id=parts_by_id,
                        invoice_type="CR",
                        net_factor=1.0,
                        profile=profile,
                    )
                    contributions.extend(built_rows)
                    unresolved_titles.extend(issues)
                    source_stats["positions_included"] += len(built_rows)
                    source_stats["titles_unresolved"] += len(issues)
                    continue
                for pos in document_positions:
                    built = self._build_contribution(
                        source_kind="credit_note",
                        document=credit,
                        position=pos,
                        parts_by_id=parts_by_id,
                        profile_category_ids=profile_category_ids,
                        invoice_type="CR",
                        net_factor=1.0,
                    )
                    if built is None:
                        source_stats["positions_skipped_no_profile_match"] += 1
                        continue
                    source_stats["positions_included"] += 1
                    contributions.append(built)
                    if built.warning:
                        anomalies.append(built.warning)

        unresolved_titles = list(
            {
                (
                    item.raw_title,
                    item.document_number,
                    item.order_reference,
                    item.sku,
                    item.reason,
                ): item
                for item in unresolved_titles
            }.values()
        )
        anomalies.extend(
            f"{item.sku} · {item.document_number}: {item.reason}"
            + (f" ({item.raw_title})" if item.raw_title else "")
            for item in unresolved_titles
        )
        product_rows = self._aggregate_products(
            contributions, group_by_name=profile.resolve_unreleased_titles
        )
        category_rows = self._aggregate_categories(contributions)
        summary = CommissionSummary(
            total_net_quantity=sum(item.signed_quantity for item in contributions),
            total_net_amount=sum(item.signed_net for item in contributions),
            total_gross_amount=sum(item.signed_gross for item in contributions),
            total_correction_quantity=sum(
                abs(item.signed_quantity) for item in contributions if item.signed_quantity < 0
            ),
            document_count=len({item.document_id for item in contributions}),
            anomaly_count=len(anomalies),
        )

        contributions.sort(key=lambda item: (item.document_date, item.document_number, item.sku))

        return CommissionRunResult(
            profile=profile,
            period=period,
            summary=summary,
            product_rows=product_rows,
            category_rows=category_rows,
            document_rows=contributions,
            anomalies=anomalies,
            source_stats=source_stats,
            unresolved_titles=unresolved_titles,
        )

    def _build_unreleased_contributions(
        self,
        *,
        source_kind: str,
        document: dict[str, Any],
        positions: list[dict[str, Any]],
        parts_by_id: dict[str, dict[str, Any]],
        invoice_type: str,
        net_factor: float,
        profile: CommissionProfile,
    ) -> tuple[list[DocumentContribution], list[UnreleasedResolutionIssue]]:
        """Resolve special-SKU position totals through Wix titles and the alias catalog."""
        base_rows: list[DocumentContribution] = []
        for position in positions:
            built = self._build_contribution(
                source_kind=source_kind,
                document=document,
                position=position,
                parts_by_id=parts_by_id,
                profile_category_ids=set(),
                profile_sku_patterns=profile.sku_patterns,
                invoice_type=invoice_type,
                net_factor=net_factor,
            )
            if built is not None:
                base_rows.append(built)
        if not base_rows:
            return [], []
        base_rows = _combine_document_rows_by_sku(base_rows)

        reference = _document_wix_reference(document)
        wix_titles: dict[str, list[str]] = {}
        if reference and self._wix_orders is not None:
            for item in self._wix_orders.fetch_order_line_items(reference):
                sku = str(getattr(item, "sku", "") or "").strip().upper()
                if not _matches_any_pattern(sku, profile.sku_patterns):
                    continue
                raw_titles = [
                    str(title).strip()
                    for title in (getattr(item, "custom_piece_titles", None) or [])
                    if str(title).strip()
                ]
                if not raw_titles:
                    fallback = str(getattr(item, "name", "") or "").strip()
                    if fallback:
                        raw_titles = [fallback]
                quantity = max(1, int(getattr(item, "qty", 1) or 1))
                titles = (
                    self._product_catalog.split_unreleased_titles(raw_titles, quantity)
                    if self._product_catalog is not None
                    else raw_titles
                )
                wix_titles.setdefault(sku, []).extend(titles)

        results: list[DocumentContribution] = []
        issues: list[UnreleasedResolutionIssue] = []
        for base in base_rows:
            titles = wix_titles.get(base.sku.upper(), [])
            override_key = reference or base.document_number
            manual_title = (
                self._product_catalog.unreleased_document_title(override_key)
                if self._product_catalog is not None
                else ""
            )
            if manual_title:
                titles = [line.strip() for line in manual_title.splitlines() if line.strip()]
            if not titles:
                candidate = base.name
                if normalize_unreleased_position_name(candidate):
                    titles = [candidate]
            if not titles:
                issues.append(
                    UnreleasedResolutionIssue(
                        raw_title="",
                        document_number=base.document_number,
                        order_reference=reference,
                        sku=base.sku,
                        reason="Kein Stücktitel in der zugehörigen Wix-Bestellung gefunden",
                        quantity=max(1, int(round(abs(base.signed_quantity)))),
                        needs_title_split=True,
                    )
                )
                continue

            expected_quantity = max(1, int(round(abs(base.signed_quantity))))
            if len(titles) != expected_quantity:
                issues.append(
                    UnreleasedResolutionIssue(
                        raw_title="\n".join(titles),
                        document_number=base.document_number,
                        order_reference=reference,
                        sku=base.sku,
                        reason=(
                            f"{expected_quantity} Stücktitel erwartet, aber {len(titles)} erkannt"
                        ),
                        quantity=expected_quantity,
                        needs_title_split=True,
                    )
                )
                continue

            quantity_weight = abs(base.signed_quantity)
            per_title_weight = quantity_weight / len(titles) if quantity_weight else 0.0
            for title in titles:
                resolution = (
                    self._product_catalog.resolve_unreleased_title(title)
                    if self._product_catalog is not None
                    else None
                )
                if resolution is None or not resolution.is_resolved:
                    reason = "Alias nicht eindeutig"
                    if (
                        resolution is not None
                        and resolution.canonical_name
                        and not resolution.owner
                    ):
                        reason = "Für das Produkt ist keine eindeutige Gattung hinterlegt"
                    issues.append(
                        UnreleasedResolutionIssue(
                            raw_title=title,
                            document_number=base.document_number,
                            order_reference=reference,
                            sku=base.sku,
                            reason=reason,
                            quantity=1,
                        )
                    )
                    continue
                ratio = 1.0 / expected_quantity
                signed_quantity = (
                    -per_title_weight if base.signed_quantity < 0 else per_title_weight
                )
                results.append(
                    replace(
                        base,
                        name=resolution.canonical_name,
                        category_name=resolution.owner,
                        raw_quantity=abs(base.raw_quantity) * ratio,
                        raw_net=base.raw_net * ratio,
                        raw_gross=base.raw_gross * ratio,
                        signed_quantity=signed_quantity,
                        signed_net=base.signed_net * ratio,
                        signed_gross=base.signed_gross * ratio,
                        rule=f"{base.rule}:unreleased-{resolution.method}",
                    )
                )
        return results, issues

    def _load_profiles(self, profile_config_path: Path | None) -> dict[str, CommissionProfile]:
        profiles: dict[str, CommissionProfile] = {}
        for profile in _default_profiles().values():
            profiles[profile.key] = profile

        config_path = profile_config_path or _default_profile_config_path()
        if not config_path.exists():
            return profiles

        try:
            with config_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Commission profile config load failed (%s): %s", config_path, exc)
            return profiles

        raw_profiles = payload.get("profiles") if isinstance(payload, dict) else payload
        if not isinstance(raw_profiles, list):
            logger.warning("Commission profile config has no list: %s", config_path)
            return profiles

        for raw in raw_profiles:
            if not isinstance(raw, dict):
                continue
            profile = _profile_from_dict(raw)
            if profile is None:
                continue
            profiles[profile.key] = profile
        return profiles

    def _build_contribution(
        self,
        *,
        source_kind: str,
        document: dict[str, Any],
        position: dict[str, Any],
        parts_by_id: dict[str, dict[str, Any]],
        profile_category_ids: set[str],
        profile_sku_patterns: tuple[str, ...] = (),
        invoice_type: str,
        net_factor: float,
    ) -> DocumentContribution | None:
        raw_quantity = _to_float(
            position.get("quantity") or position.get("qty") or position.get("count")
        )
        raw_net = _to_float(
            position.get("sumNet")
            or position.get("priceNet")
            or position.get("sumNetAccounting")
            or position.get("price")
        )
        raw_gross = _to_float(
            position.get("sumGross") or position.get("priceGross") or position.get("price")
        )
        adjusted_net = raw_net * net_factor
        adjusted_gross = raw_gross * net_factor

        part_obj = position.get("part") if isinstance(position.get("part"), dict) else {}
        part_id = str(
            part_obj.get("id")
            or _reference_id(position.get("part"))
            or _reference_id(position.get("partId"))
            or ""
        ).strip()
        part_meta = parts_by_id.get(part_id, {}) if part_id else {}

        # A category profile must only contain real sevDesk products whose current
        # catalog record carries the configured category.  Free-text positions and
        # ambiguous name fallbacks are deliberately not eligible.
        if not part_meta:
            return None

        category_id = str(part_meta.get("category_id") or "").strip()
        category_name = str(part_meta.get("category_name") or "").strip()
        part_sku = str(part_meta.get("sku") or part_obj.get("partNumber") or "").strip()
        category_match = bool(category_id and category_id in profile_category_ids)
        sku_match = _matches_any_pattern(part_sku, profile_sku_patterns)
        if not category_match and not sku_match:
            return None

        sku = (
            str(
                part_meta.get("sku")
                or part_obj.get("partNumber")
                or position.get("partNumber")
                or position.get("name")
                or ""
            ).strip()
            or "(ohne-sku)"
        )
        name = (
            str(
                part_meta.get("name")
                or part_obj.get("name")
                or position.get("name")
                or position.get("text")
                or ""
            ).strip()
            or "(ohne Bezeichnung)"
        )

        doc_number = _document_number(document)
        doc_id = str(document.get("id") or "").strip()
        doc_date = _pick_date(
            document, ("creditNoteDate", "invoiceDate", "date", "create", "updated")
        )
        doc_date_iso = doc_date.isoformat() if doc_date is not None else ""

        warning = ""
        if source_kind == "invoice":
            is_cancel = invoice_type in _CANCEL_INVOICE_TYPES
            signed_quantity = -abs(raw_quantity) if is_cancel else abs(raw_quantity)
            signed_net = adjusted_net
            signed_gross = adjusted_gross
            rule = f"invoice:discount:{net_factor:.6f}" if net_factor < 1.0 else "invoice:standard"
            if is_cancel:
                rule = "invoice:sr-cancel"
                if adjusted_net > 0:
                    signed_net = -abs(adjusted_net)
                    warning = (
                        f"{sku}: SR-Beleg {doc_number} mit positivem Roh-Netto erkannt, "
                        "Vorzeichen korrigiert"
                    )
                if adjusted_gross > 0:
                    signed_gross = -abs(adjusted_gross)
        else:
            signed_quantity = -abs(raw_quantity)
            signed_net = raw_net if raw_net <= 0 else -abs(raw_net)
            signed_gross = raw_gross if raw_gross <= 0 else -abs(raw_gross)
            rule = "credit-note"

        if signed_quantity < 0 and signed_net > 0 and not warning:
            warning = f"{sku}: Netto positiv trotz negativer Menge ({doc_number})"
        elif abs(signed_quantity) < 1e-9 and abs(signed_net) > 1e-6 and not warning:
            warning = f"{sku}: Menge 0 bei Umsatz != 0 ({doc_number})"

        return DocumentContribution(
            document_id=doc_id,
            document_number=doc_number,
            document_type=invoice_type if source_kind == "invoice" else "CR",
            document_date=doc_date_iso,
            source_kind=source_kind,
            sku=sku,
            name=name,
            category_name=category_name,
            raw_quantity=raw_quantity,
            raw_net=raw_net,
            raw_gross=raw_gross,
            signed_quantity=signed_quantity,
            signed_net=signed_net,
            signed_gross=signed_gross,
            rule=rule,
            warning=warning,
        )

    @staticmethod
    def _aggregate_products(
        contributions: list[DocumentContribution], *, group_by_name: bool = False
    ) -> list[ProductBreakdownRow]:
        rows: dict[tuple[str, str], ProductBreakdownRow] = {}
        category_sets: dict[tuple[str, str], set[str]] = {}
        sku_sets: dict[tuple[str, str], set[str]] = {}

        for item in contributions:
            key = ("", item.name) if group_by_name else (item.sku, item.name)
            row = rows.get(key)
            if row is None:
                row = ProductBreakdownRow(sku=item.sku, name=item.name)
                rows[key] = row
                category_sets[key] = set()
                sku_sets[key] = set()
            sku_sets[key].add(item.sku)

            if item.source_kind == "invoice" and item.document_type in _CANCEL_INVOICE_TYPES:
                row.canceled_quantity += abs(item.signed_quantity)
            elif item.source_kind == "credit_note":
                row.credited_quantity += abs(item.signed_quantity)
            else:
                row.sold_quantity += abs(item.signed_quantity)

            row.net_quantity += item.signed_quantity
            row.net_amount += item.signed_net
            row.gross_amount += item.signed_gross

            if item.category_name:
                category_sets[key].add(item.category_name)
            if item.warning and not row.warning:
                row.warning = item.warning

        for key, row in rows.items():
            names = sorted(category_sets.get(key, set()))
            row.category_names = tuple(names)
            row.sku = " / ".join(sorted(sku_sets.get(key, {row.sku})))

        result = list(rows.values())
        result.sort(key=lambda row: (row.net_amount, row.net_quantity), reverse=True)
        return result

    @staticmethod
    def _aggregate_categories(
        contributions: list[DocumentContribution],
    ) -> list[CategoryBreakdownRow]:
        rows: dict[str, CategoryBreakdownRow] = {}
        total_net = sum(item.signed_net for item in contributions)

        for item in contributions:
            category_name = item.category_name or "(ohne Kategorie)"
            row = rows.get(category_name)
            if row is None:
                row = CategoryBreakdownRow(category_name=category_name)
                rows[category_name] = row
            row.quantity += item.signed_quantity
            row.net_amount += item.signed_net
            row.gross_amount += item.signed_gross

        for row in rows.values():
            if abs(total_net) > 1e-9:
                row.share_of_net_amount = row.net_amount / total_net
            else:
                row.share_of_net_amount = 0.0

        result = list(rows.values())
        result.sort(key=lambda row: row.net_amount, reverse=True)
        return result


def _year_bounds_timestamps(year: int) -> tuple[int, int]:
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    return int(start.timestamp()), int(end.timestamp())


def _to_float(value: object) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _format_de_number(value: float, *, trim: bool = False) -> str:
    formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if trim:
        formatted = formatted.rstrip("0").rstrip(",")
    return formatted


def _pick_date(payload: dict[str, Any], keys: tuple[str, ...]) -> date | None:
    for key in keys:
        value = payload.get(key)
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
    return None


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    head = text[:10]
    for candidate in (head, text):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _shift_months(input_date: date, delta_months: int) -> date:
    month_index = input_date.year * 12 + (input_date.month - 1) + delta_months
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(input_date.day, _month_end(year, month).day)
    return date(year, month, day)


def _reference_id(value: object) -> str:
    if isinstance(value, dict):
        inner = value.get("id")
        if inner is not None:
            return str(inner)
    if value is None:
        return ""
    return str(value)


def _group_positions_by_parent(
    positions: list[dict[str, Any]], parent_key: str
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for position in positions:
        parent_id = _reference_id(position.get(parent_key)).strip()
        if parent_id:
            grouped.setdefault(parent_id, []).append(position)
    return grouped


def _combine_document_rows_by_sku(
    rows: list[DocumentContribution],
) -> list[DocumentContribution]:
    """Combine repeated generic SKU positions before distributing their Wix titles."""
    grouped: dict[str, DocumentContribution] = {}
    for row in rows:
        key = row.sku.upper()
        current = grouped.get(key)
        if current is None:
            grouped[key] = row
            continue
        grouped[key] = replace(
            current,
            raw_quantity=current.raw_quantity + row.raw_quantity,
            raw_net=current.raw_net + row.raw_net,
            raw_gross=current.raw_gross + row.raw_gross,
            signed_quantity=current.signed_quantity + row.signed_quantity,
            signed_net=current.signed_net + row.signed_net,
            signed_gross=current.signed_gross + row.signed_gross,
            warning=current.warning or row.warning,
        )
    return list(grouped.values())


def _is_draft_document(document: dict[str, Any]) -> bool:
    return int(_to_float(document.get("status"))) == 100


def _invoice_discount_factor(invoice: dict[str, Any], positions: list[dict[str, Any]]) -> float:
    """Return the proportional net factor for a sevDesk header discount."""
    net_before_discount = sum(_to_float(position.get("sumNet")) for position in positions)
    discount_net = abs(
        _to_float(invoice.get("sumDiscountNet") or invoice.get("sumDiscounts") or 0.0)
    )
    if net_before_discount <= 0.0 or discount_net <= 0.0:
        return 1.0
    return max(0.0, 1.0 - min(discount_net / net_before_discount, 1.0))


def _document_number(document: dict[str, Any]) -> str:
    for key in ("invoiceNumber", "creditNoteNumber", "voucherNumber", "number", "id"):
        value = str(document.get(key) or "").strip()
        if value:
            return value
    return ""


def _document_wix_reference(document: dict[str, Any]) -> str:
    for key in ("reference", "orderReference", "customerInternalNote"):
        raw = str(document.get(key) or "").strip()
        reference = extract_wix_order_number(raw)
        if reference:
            return reference
        if raw.isdigit():
            return raw
    return ""


def _matches_any_pattern(value: str, patterns: tuple[str, ...]) -> bool:
    normalized = str(value or "").strip().upper()
    return any(re.fullmatch(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)


def normalize_unreleased_position_name(value: str) -> str:
    """Return a usable title or empty text for generic sevDesk labels."""
    title = " ".join(str(value or "").split()).strip()
    normalized = normalize_legacy_title(title)
    generic_tokens = (
        "diverse noten unveroffentlicht",
        "div noten unveroffentlicht",
        "unveroffentlichte noten",
        "xw 010",
    )
    if not title or any(token in normalized for token in generic_tokens):
        return ""
    return title


def _default_profile_config_path() -> Path:
    root = Path(__file__).resolve().parents[4]
    return root / "config" / "commission_profiles.yaml"


def _default_profiles() -> dict[str, CommissionProfile]:
    musikheroes = CommissionProfile(
        key="musikheroes",
        label="MusikHeroes",
        category_names=(
            "MusikHeroes",
            "MusikHeroes_Noten digital",
            "MusikHeroes_Playalongs digital",
            "MusikHeroes_Print@Home",
        ),
        include_credit_notes=True,
        include_cancellation_invoices=True,
        date_policy="invoice_date",
    )
    return {musikheroes.key: musikheroes}


def _profile_from_dict(raw: dict[str, Any]) -> CommissionProfile | None:
    key = str(raw.get("key") or "").strip()
    if not key:
        return None
    label = str(raw.get("label") or key).strip() or key
    category_names_raw = raw.get("category_names")
    category_names: tuple[str, ...]
    if isinstance(category_names_raw, list):
        category_names = tuple(
            str(item).strip() for item in category_names_raw if str(item).strip()
        )
    else:
        category_names = ()
    include_credit_notes = bool(raw.get("include_credit_notes", True))
    include_cancellation_invoices = bool(raw.get("include_cancellation_invoices", True))
    date_policy = str(raw.get("date_policy") or "invoice_date").strip() or "invoice_date"
    commission_rate_percent = _to_float(raw.get("commission_rate_percent"))
    sku_patterns_raw = raw.get("sku_patterns")
    sku_patterns = (
        tuple(str(item).strip() for item in sku_patterns_raw if str(item).strip())
        if isinstance(sku_patterns_raw, list)
        else ()
    )
    resolve_unreleased_titles = bool(raw.get("resolve_unreleased_titles", False))

    return CommissionProfile(
        key=key,
        label=label,
        category_names=category_names,
        commission_rate_percent=commission_rate_percent,
        sku_patterns=sku_patterns,
        resolve_unreleased_titles=resolve_unreleased_titles,
        include_credit_notes=include_credit_notes,
        include_cancellation_invoices=include_cancellation_invoices,
        date_policy=date_policy,
    )
