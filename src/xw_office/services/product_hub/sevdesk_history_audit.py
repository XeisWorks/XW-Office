"""Read-only audit of finalized sevDesk sales/credit history for forecasting."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
from collections.abc import Iterable
from typing import Any, Protocol


class SevdeskHistoryProvider(Protocol):
    def list_invoices_for_year(self, year: int) -> list[dict[str, Any]]: ...
    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, Any]]: ...
    def list_credit_notes_for_year(self, year: int) -> list[dict[str, Any]]: ...
    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, Any]]: ...


class SevdeskMonthlyHistoryProvider(Protocol):
    """Small monthly sevDesk source used by the production history adapter."""

    def load_invoices(self, year: int, month: int) -> list[dict[str, Any]]: ...
    def load_credit_notes(self, year: int, month: int) -> list[dict[str, Any]]: ...
    def load_positions(self, resource: str, document_id: str) -> list[dict[str, Any]]: ...


class SevdeskHistoryProviderAdapter:
    """Adapt the existing month-filtered sevDesk client to the forecast protocol.

    The tax client already owns the proven pagination/date-filter behavior. This
    adapter only groups those read calls by year and never performs a write.
    """

    def __init__(self, monthly_provider: SevdeskMonthlyHistoryProvider) -> None:
        self._monthly = monthly_provider

    def list_invoices_for_year(self, year: int) -> list[dict[str, Any]]:
        return self._deduplicate(
            row
            for month in range(1, 13)
            for row in self._monthly.load_invoices(year, month)
        )

    def list_credit_notes_for_year(self, year: int) -> list[dict[str, Any]]:
        return self._deduplicate(
            row
            for month in range(1, 13)
            for row in self._monthly.load_credit_notes(year, month)
        )

    def list_invoice_positions(self, invoice_id: str) -> list[dict[str, Any]]:
        return self._monthly.load_positions("Invoice", invoice_id)

    def list_credit_note_positions(self, credit_note_id: str) -> list[dict[str, Any]]:
        return self._monthly.load_positions("CreditNote", credit_note_id)

    def list_invoice_positions_bulk(self, invoice_ids: list[str]) -> list[dict[str, Any]]:
        return self._list_positions_bulk("Invoice", "invoice", invoice_ids)

    def list_credit_note_positions_bulk(self, credit_note_ids: list[str]) -> list[dict[str, Any]]:
        return self._list_positions_bulk("CreditNote", "creditNote", credit_note_ids)

    def _list_positions_bulk(
        self, resource: str, parent_key: str, document_ids: list[str]
    ) -> list[dict[str, Any]]:
        ids = {str(item).strip() for item in document_ids if str(item).strip()}
        loader = getattr(self._monthly, "load_positions_bulk", None)
        if not ids or not callable(loader):
            single = self.list_invoice_positions if resource == "Invoice" else self.list_credit_note_positions
            return [position for document_id in ids for position in single(document_id)]
        rows = loader(resource)
        selected: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            parent = row.get(parent_key)
            parent_id = str(parent.get("id") if isinstance(parent, dict) else parent or "").strip()
            if parent_id in ids:
                selected.append(dict(row))
        return selected

    def list_final_invoices(self, *, since: datetime.date | None = None) -> list[dict[str, Any]]:
        default_since = datetime.date.today().replace(year=datetime.date.today().year - 5)
        start_year = (since or default_since).year
        end_year = datetime.date.today().year
        result: list[dict[str, Any]] = []
        for year in range(start_year, end_year + 1):
            for row in self.list_invoices_for_year(year):
                if _is_draft(row):
                    continue
                if since is not None:
                    occurred = _parse_date(row, ("invoiceDate", "date", "create", "updated"))
                    if occurred is None or occurred < since:
                        continue
                result.append(row)
        return result

    @staticmethod
    def _deduplicate(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id") or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            result.append(dict(row))
        return result


def sevdesk_history_provider_from_connection(connection: Any) -> SevdeskHistoryProviderAdapter:
    """Create the production adapter on top of the existing sevDesk connection."""
    from xw_office.services.finanzonline.zm_service import SevdeskZmInvoiceProvider

    return SevdeskHistoryProviderAdapter(SevdeskZmInvoiceProvider(connection))


@dataclass(frozen=True)
class SevdeskHistoryAudit:
    window_start: datetime.date
    window_end: datetime.date
    invoice_count: int
    credit_note_count: int
    product_position_count: int
    net_units: int
    first_sale_date: datetime.date | None
    last_sale_date: datetime.date | None
    full_months_covered: int
    issues: tuple[str, ...]

    @property
    def complete_five_year_window(self) -> bool:
        return self.full_months_covered >= 60 and not self.issues


def audit_sevdesk_history(
    provider: SevdeskHistoryProvider,
    *,
    as_of: datetime.date | None = None,
    years: int = 5,
) -> SevdeskHistoryAudit:
    """Read finalized positions only; never writes stock or booking rows."""
    today = as_of or datetime.date.today()
    first_of_current = today.replace(day=1)
    window_end = first_of_current - datetime.timedelta(days=1)
    start_month_index = (window_end.year * 12 + window_end.month - 1) - (years * 12 - 1)
    window_start = datetime.date(start_month_index // 12, start_month_index % 12 + 1, 1)
    invoice_count = credit_count = position_count = net_units = 0
    dates: list[datetime.date] = []
    issues: list[str] = []
    for year in range(window_start.year, window_end.year + 1):
        for invoice in provider.list_invoices_for_year(year):
            if _is_draft(invoice):
                continue
            doc_date = _parse_date(invoice, ("invoiceDate", "date", "create", "updated"))
            if doc_date is None or not (window_start <= doc_date <= window_end):
                continue
            invoice_count += 1
            positions = provider.list_invoice_positions(str(invoice.get("id") or ""))
            for position in positions:
                units = _position_units(position)
                if units <= 0:
                    continue
                position_count += 1
                net_units += units
                dates.append(doc_date)
                if not _position_sku(position):
                    issues.append(f"Rechnung {invoice.get('id')}: Position ohne SKU")
        for credit in provider.list_credit_notes_for_year(year):
            if _is_draft(credit):
                continue
            doc_date = _parse_date(credit, ("creditNoteDate", "invoiceDate", "date", "create", "updated"))
            if doc_date is None or not (window_start <= doc_date <= window_end):
                continue
            credit_count += 1
            positions = provider.list_credit_note_positions(str(credit.get("id") or ""))
            for position in positions:
                units = _position_units(position)
                if units <= 0:
                    continue
                position_count += 1
                net_units -= units
                dates.append(doc_date)
                if not _position_sku(position):
                    issues.append(f"Gutschrift {credit.get('id')}: Position ohne SKU")
    full_months = _full_months_between(window_start, window_end)
    first_date = min(dates) if dates else None
    last_date = max(dates) if dates else None
    if not dates:
        issues.append("Keine finalen Produktpositionen im Prüfzeitraum")
    if full_months < 60:
        issues.append(f"Prüfzeitraum umfasst nur {full_months} volle Monate")
    return SevdeskHistoryAudit(
        window_start=window_start, window_end=window_end,
        invoice_count=invoice_count, credit_note_count=credit_count,
        product_position_count=position_count, net_units=net_units,
        first_sale_date=first_date, last_sale_date=last_date,
        full_months_covered=full_months, issues=tuple(dict.fromkeys(issues)),
    )


def _is_draft(document: dict[str, Any]) -> bool:
    raw_status = document.get("status")
    if raw_status is None:
        return False
    try:
        return int(raw_status) == 100
    except (TypeError, ValueError):
        return str(raw_status).strip().casefold() in {"draft", "entwurf"}


def _parse_date(document: dict[str, Any], keys: tuple[str, ...]) -> datetime.date | None:
    for key in keys:
        raw = str(document.get(key) or "").strip()
        if not raw:
            continue
        try:
            return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.date.fromisoformat(raw[:10])
            except ValueError:
                continue
    return None


def _position_units(position: dict[str, Any]) -> int:
    raw = position.get("quantity", position.get("qty", position.get("amount", 0)))
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return 0


def _position_sku(position: dict[str, Any]) -> str:
    raw_part = position.get("part")
    part = raw_part if isinstance(raw_part, dict) else {}
    return str(position.get("sku") or position.get("partNumber") or part.get("number") or "").strip()


def _full_months_between(start: datetime.date, end: datetime.date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month + 1)


__all__ = [
    "SevdeskHistoryAudit",
    "SevdeskHistoryProvider",
    "SevdeskHistoryProviderAdapter",
    "SevdeskMonthlyHistoryProvider",
    "audit_sevdesk_history",
    "sevdesk_history_provider_from_connection",
]
