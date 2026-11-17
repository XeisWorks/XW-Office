"""Small, durable shipping plan shared by START and its run history."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.shipping.countries import country_iso2


EU_CH_CODES = frozenset({
    "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
    "RO", "SE", "SI", "SK", "CH",
})
def country_code(value: object) -> str:
    return country_iso2(value)


def compact_customer_name(name: object, *, company: object = "") -> str:
    """Show a company alone in compact buyer lists; keep personal names otherwise."""
    firm = str(company or "").strip()
    if firm:
        return firm
    text = str(name or "").strip()
    for separator in (" | ", " / "):
        if separator in text:
            return text.split(separator, 1)[0].strip()
    return text


def missing_customer_name(value: object) -> bool:
    return str(value or "").strip().casefold() in {
        "", "-", "—", "---", "käufer nicht verfügbar", "kunde nicht verfügbar",
    }


@dataclass(frozen=True)
class ShippingCandidate:
    invoice_id: str
    invoice_date: str
    customer_name: str
    order_reference: str
    lane: str  # at, abroad, digital
    eu_ch: bool = False
    plc: bool = False


def candidate_from_summary(
    summary: InvoiceSummary,
    *,
    wix_name: str = "",
    wix_company: str = "",
    wix_country: str = "",
    digital_only: bool = False,
    plc: bool = False,
) -> ShippingCandidate:
    country = country_code(wix_country) or country_code(summary.display_country)
    is_plc = plc or summary.has_plc_label_candidate()
    lane = "digital" if digital_only else "at" if is_plc or country == "AT" else "abroad"
    contact_name = str(summary.contact_name or "").strip()
    contact_company = (
        compact_customer_name(contact_name)
        if any(separator in contact_name for separator in (" | ", " / "))
        else ""
    )
    return ShippingCandidate(
        invoice_id=str(summary.id),
        invoice_date=str(summary.invoice_date or ""),
        customer_name=(
            compact_customer_name(wix_name, company=wix_company or contact_company)
            or compact_customer_name(contact_name) or "—"
        ),
        order_reference=str(summary.order_reference or "").strip(),
        lane=lane,
        eu_ch=country in EU_CH_CODES,
        plc=is_plc,
    )


def pending_abroad(records: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [
        row for row in records.values()
        if isinstance(row, dict)
        and row.get("lane") == "abroad"
        and row.get("planned_date")
        and not row.get("shipped_date")
    ]


def abroad_with_at_default(
    candidates: list[ShippingCandidate],
    pending: list[dict[str, str]],
) -> bool:
    """Usually hold a small EU/CH batch; other destinations remain operator choice."""
    eu_count = sum(row.eu_ch for row in candidates if row.lane == "abroad")
    eu_count += sum(row.get("eu_ch") == "1" for row in pending)
    return eu_count >= 3


def valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
