"""Commission calculations with sevDesk-backed document aggregation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
from typing import Any, Protocol

import yaml

from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.sevdesk.part_client import PartClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_MAX_PAGES = 200
_CANCEL_INVOICE_TYPES = {"SR"}


@dataclass(frozen=True)
class CommissionProfile:
    """Configuration of one commission analysis profile."""

    key: str
    label: str
    category_names: tuple[str, ...]
    include_credit_notes: bool = True
    include_cancellation_invoices: bool = True
    date_policy: str = "invoice_date"


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


class CommissionDataProvider(Protocol):
    """Abstract data source used by commission calculations."""

    def list_part_categories(self) -> list[dict[str, str]]:
        ...

    def list_parts(self) -> list[dict[str, Any]]:
        ...

    def list_invoices_for_year(self, year: int) -> list[dict[str, Any]]:
        ...

    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, Any]]:
        ...

    def list_credit_notes_for_year(self, year: int) -> list[dict[str, Any]]:
        ...

    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, Any]]:
        ...


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
        self._parts_cache: list[dict[str, Any]] | None = None
        self._categories_cache: list[dict[str, str]] | None = None

    def clear_cache(self) -> None:
        self._invoice_cache.clear()
        self._credit_cache.clear()
        self._invoice_pos_cache.clear()
        self._credit_pos_cache.clear()
        self._parts_cache = None
        self._categories_cache = None

    def list_part_categories(self) -> list[dict[str, str]]:
        if self._categories_cache is None:
            self._categories_cache = self._part_client.list_part_categories()
        return [dict(item) for item in self._categories_cache]

    def list_parts(self) -> list[dict[str, Any]]:
        if self._parts_cache is None:
            self._parts_cache = [row.model_dump() for row in self._part_client.list_parts(refresh_cache=True)]
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
                dict(item) for item in objects if isinstance(objects, list) and isinstance(item, dict)
            ]
        return [dict(item) for item in self._invoice_pos_cache[doc_id]]

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
                dict(item) for item in objects if isinstance(objects, list) and isinstance(item, dict)
            ]
        return [dict(item) for item in self._credit_pos_cache[doc_id]]

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
        return result


class CommissionService:
    """Business logic for commission runs and profile filtering."""

    def __init__(
        self,
        provider: CommissionDataProvider | None = None,
        *,
        profile_config_path: Path | None = None,
    ) -> None:
        self._provider = provider
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
            first_of_current = date(today.year, today.month, 1)
            end = first_of_current - timedelta(days=1)
            half_year_start = _shift_months(date(end.year, end.month, 1), -5)
            start = date(half_year_start.year, half_year_start.month, 1)
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
        use_credit_notes = profile.include_credit_notes if include_credit_notes is None else include_credit_notes

        categories = self._provider.list_part_categories()
        category_name_to_id = {
            str(item.get("name") or "").strip(): str(item.get("id") or "").strip()
            for item in categories
            if str(item.get("name") or "").strip() and str(item.get("id") or "").strip()
        }
        profile_category_ids = {
            category_name_to_id[name]
            for name in profile.category_names
            if name in category_name_to_id
        }

        parts = self._provider.list_parts()
        parts_by_id = {
            str(part.get("id") or "").strip(): part for part in parts if str(part.get("id") or "").strip()
        }

        source_stats: dict[str, int] = {
            "invoices_loaded": 0,
            "invoice_positions_loaded": 0,
            "credit_notes_loaded": 0,
            "credit_positions_loaded": 0,
            "positions_included": 0,
            "positions_skipped_no_profile_match": 0,
            "positions_skipped_missing_date": 0,
        }

        anomalies: list[str] = []
        contributions: list[DocumentContribution] = []
        years = range(period.start.year, period.end.year + 1)

        for year in years:
            invoices = self._provider.list_invoices_for_year(year)
            source_stats["invoices_loaded"] += len(invoices)
            for invoice in invoices:
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
                positions = self._provider.list_invoice_positions(invoice_id)
                source_stats["invoice_positions_loaded"] += len(positions)
                for pos in positions:
                    built = self._build_contribution(
                        source_kind="invoice",
                        document=invoice,
                        position=pos,
                        parts_by_id=parts_by_id,
                        profile=profile,
                        profile_category_ids=profile_category_ids,
                        invoice_type=invoice_type,
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
            for credit in credit_notes:
                doc_date = _pick_date(credit, ("creditNoteDate", "date", "create", "updated"))
                if doc_date is None:
                    source_stats["positions_skipped_missing_date"] += 1
                    continue
                if doc_date < period.start or doc_date > period.end:
                    continue

                credit_id = str(credit.get("id") or "").strip()
                if not credit_id:
                    continue
                positions = self._provider.list_credit_note_positions(credit_id)
                source_stats["credit_positions_loaded"] += len(positions)
                for pos in positions:
                    built = self._build_contribution(
                        source_kind="credit_note",
                        document=credit,
                        position=pos,
                        parts_by_id=parts_by_id,
                        profile=profile,
                        profile_category_ids=profile_category_ids,
                        invoice_type="CR",
                    )
                    if built is None:
                        source_stats["positions_skipped_no_profile_match"] += 1
                        continue
                    source_stats["positions_included"] += 1
                    contributions.append(built)
                    if built.warning:
                        anomalies.append(built.warning)

        product_rows = self._aggregate_products(contributions)
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
        )

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
        profile: CommissionProfile,
        profile_category_ids: set[str],
        invoice_type: str,
    ) -> DocumentContribution | None:
        raw_quantity = _to_float(position.get("quantity") or position.get("qty") or position.get("count"))
        raw_net = _to_float(
            position.get("sumNet")
            or position.get("priceNet")
            or position.get("sumNetAccounting")
            or position.get("price")
        )
        raw_gross = _to_float(position.get("sumGross") or position.get("priceGross") or position.get("price"))

        part_obj = position.get("part") if isinstance(position.get("part"), dict) else {}
        part_id = str(
            part_obj.get("id")
            or _reference_id(position.get("part"))
            or _reference_id(position.get("partId"))
            or ""
        ).strip()
        part_meta = parts_by_id.get(part_id, {}) if part_id else {}

        category_id = str(
            part_meta.get("category_id")
            or _nested_id(part_obj.get("category"))
            or _nested_id(position.get("category"))
            or ""
        ).strip()
        category_name = str(
            part_meta.get("category_name")
            or _nested_name(part_obj.get("category"))
            or _nested_name(position.get("category"))
            or ""
        ).strip()

        matches_profile = False
        if profile_category_ids and category_id:
            matches_profile = category_id in profile_category_ids
        if not matches_profile and category_name:
            matches_profile = category_name in profile.category_names
        if not matches_profile:
            return None

        sku = str(
            part_meta.get("sku")
            or part_obj.get("partNumber")
            or position.get("partNumber")
            or position.get("name")
            or ""
        ).strip() or "(ohne-sku)"
        name = str(
            part_meta.get("name")
            or part_obj.get("name")
            or position.get("name")
            or position.get("text")
            or ""
        ).strip() or "(ohne Bezeichnung)"

        doc_number = _document_number(document)
        doc_id = str(document.get("id") or "").strip()
        doc_date = _pick_date(document, ("creditNoteDate", "invoiceDate", "date", "create", "updated"))
        doc_date_iso = doc_date.isoformat() if doc_date is not None else ""

        warning = ""
        if source_kind == "invoice":
            is_cancel = invoice_type in _CANCEL_INVOICE_TYPES
            signed_quantity = -abs(raw_quantity) if is_cancel else abs(raw_quantity)
            signed_net = raw_net
            signed_gross = raw_gross
            rule = "invoice:standard"
            if is_cancel:
                rule = "invoice:sr-cancel"
                if raw_net > 0:
                    signed_net = -abs(raw_net)
                    warning = (
                        f"{sku}: SR-Beleg {doc_number} mit positivem Roh-Netto erkannt, "
                        "Vorzeichen korrigiert"
                    )
                if raw_gross > 0:
                    signed_gross = -abs(raw_gross)
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
    def _aggregate_products(contributions: list[DocumentContribution]) -> list[ProductBreakdownRow]:
        rows: dict[str, ProductBreakdownRow] = {}
        category_sets: dict[str, set[str]] = {}

        for item in contributions:
            row = rows.get(item.sku)
            if row is None:
                row = ProductBreakdownRow(sku=item.sku, name=item.name)
                rows[item.sku] = row
                category_sets[item.sku] = set()

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
                category_sets[item.sku].add(item.category_name)
            if item.warning and not row.warning:
                row.warning = item.warning

        for sku, row in rows.items():
            names = sorted(category_sets.get(sku, set()))
            row.category_names = tuple(names)

        result = list(rows.values())
        result.sort(key=lambda row: (row.net_amount, row.net_quantity), reverse=True)
        return result

    @staticmethod
    def _aggregate_categories(contributions: list[DocumentContribution]) -> list[CategoryBreakdownRow]:
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


def _nested_id(value: object) -> str:
    if isinstance(value, dict):
        raw = value.get("id")
        if raw is not None:
            return str(raw)
    return ""


def _nested_name(value: object) -> str:
    if isinstance(value, dict):
        for key in ("name", "displayName"):
            raw = value.get(key)
            if raw is not None and str(raw).strip():
                return str(raw)
    return ""


def _document_number(document: dict[str, Any]) -> str:
    for key in ("invoiceNumber", "creditNoteNumber", "voucherNumber", "number", "id"):
        value = str(document.get(key) or "").strip()
        if value:
            return value
    return ""


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
        category_names = tuple(str(item).strip() for item in category_names_raw if str(item).strip())
    else:
        category_names = ()
    include_credit_notes = bool(raw.get("include_credit_notes", True))
    include_cancellation_invoices = bool(raw.get("include_cancellation_invoices", True))
    date_policy = str(raw.get("date_policy") or "invoice_date").strip() or "invoice_date"

    return CommissionProfile(
        key=key,
        label=label,
        category_names=category_names,
        include_credit_notes=include_credit_notes,
        include_cancellation_invoices=include_cancellation_invoices,
        date_policy=date_policy,
    )
