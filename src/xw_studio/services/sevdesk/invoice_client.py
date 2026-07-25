"""sevDesk Invoice API client (read-focused)."""
from __future__ import annotations

import base64
import logging
import re
from datetime import date, datetime, timezone
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.sevdesk.payment_booking import (
    book_amount_payload,
    is_paid_invoice_object,
    normalize_booking_amount,
    raise_on_error_envelope,
    response_payload,
)

logger = logging.getLogger(__name__)


def _format_date_de(raw: str | None) -> str:
    """Parse ISO date string from sevDesk and return DD.MM.YYYY."""
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return raw


def _format_amount_de(raw: str | float | None) -> str:
    """Format a decimal amount in German style: 1.234,56 €."""
    if raw is None:
        return "—"
    try:
        val = float(raw)
        # German format: dot as thousands sep, comma as decimal sep
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} €"
    except (ValueError, TypeError):
        return str(raw)

# Common sevDesk invoice status codes (subset; unknown -> label mapping default)
_INVOICE_STATUS_DE: dict[int, str] = {
    100: "Entwurf",
    200: "Offen",
    300: "Teilweise bezahlt",
    1000: "Bezahlt",
    1001: "Storniert",
}

_TABLE_STATUS_COLUMN = "🔎"


def _format_date_de_short(raw: str | None) -> str:
    """Parse ISO date string from sevDesk and return DD.MM.YY."""
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d.%m.%y")
    except (ValueError, TypeError):
        return raw

DEFAULT_SENSITIVE_COUNTRY_CODES: set[str] = {
    "AF",
    "BY",
    "IQ",
    "IR",
    "KP",
    "RU",
    "SY",
}

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_WIX_ORDER_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{5})(?!\d)")


def _extract_country_code(value: object) -> str:
    if isinstance(value, str):
        return value.strip().upper()
    if isinstance(value, dict):
        for key in ("translationCode", "code", "countryCode", "isoCode", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().upper()
        nested = value.get("country")
        if nested is not None:
            nested_code = _extract_country_code(nested)
            if nested_code:
                return nested_code
    return ""


def extract_wix_order_number(value: object) -> str:
    """Extract a five-digit Wix order number from a sevDesk reference."""
    reference = str(value or "").strip()
    if not reference or _UUID_PATTERN.fullmatch(reference):
        return ""
    if "|" in reference:
        suffix = reference.rsplit("|", 1)[-1].strip()
        if re.fullmatch(r"\d{5}", suffix):
            return suffix
    matches = _WIX_ORDER_NUMBER_PATTERN.findall(reference)
    return matches[-1] if matches else ""


class InvoiceSummary(BaseModel):
    """Normalized row for UI tables."""

    model_config = ConfigDict(extra="ignore")

    id: str
    invoice_number: str = Field(default="", alias="invoiceNumber")
    invoice_date: str | None = Field(default=None, alias="invoiceDate")
    delivery_date: str | None = Field(default=None, alias="deliveryDate")
    status_code: int | None = Field(default=None, alias="status")
    sum_gross: str | float | None = Field(default=None, alias="sumGross")
    contact_name: str = ""
    buyer_note: str = ""
    address_country_code: str = ""
    delivery_country_code: str = ""
    has_delivery_address_override: bool = False
    is_sensitive_country: bool = False
    has_unreleased_sku: bool = False
    order_reference: str = ""
    sevdesk_reference: str = ""

    @field_validator("status_code", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @field_validator(
        "id",
        "invoice_number",
        "contact_name",
        "buyer_note",
        "address_country_code",
        "delivery_country_code",
        "order_reference",
        "sevdesk_reference",
        mode="before",
    )
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @classmethod
    def from_api_object(cls, raw: dict[str, Any]) -> InvoiceSummary:
        contact = raw.get("contact")
        contact_name = ""
        if isinstance(contact, dict):
            org = str(contact.get("name") or "").strip()
            first = str(contact.get("surename") or "").strip()  # sevDesk: Vorname
            last = str(contact.get("familyname") or "").strip()
            person = f"{first} {last}".strip()
            if org and person:
                contact_name = f"{org} | {person}"
            elif org:
                contact_name = org
            else:
                contact_name = person
        cid = raw.get("id")

        country_code = ""
        for key in (
            "addressCountry",
            "addressCountryCode",
            "country",
            "countryCode",
            "invoiceAddressCountry",
        ):
            country_code = _extract_country_code(raw.get(key))
            if country_code:
                break

        if not country_code and isinstance(contact, dict):
            for key in ("addressCountry", "country", "countryCode"):
                country_code = _extract_country_code(contact.get(key))
                if country_code:
                    break
            if not country_code:
                address_obj = contact.get("address")
                if isinstance(address_obj, dict):
                    for key in ("country", "countryCode", "addressCountry"):
                        country_code = _extract_country_code(address_obj.get(key))
                        if country_code:
                            break

        delivery_country_code = ""
        for key in ("deliveryAddressCountry", "deliveryCountry", "shippingCountry"):
            delivery_country_code = _extract_country_code(raw.get(key))
            if delivery_country_code:
                break

        def _norm_text(value: object) -> str:
            return str(value or "").strip().lower()

        billing_signature = "|".join(
            _norm_text(raw.get(key))
            for key in ("street", "zip", "city", "address")
        )
        delivery_signature = "|".join(
            _norm_text(raw.get(key))
            for key in (
                "deliveryStreet",
                "deliveryZip",
                "deliveryCity",
                "deliveryAddress",
                "shippingStreet",
                "shippingZip",
                "shippingCity",
                "shippingAddress",
            )
        )
        has_delivery_override = bool(
            delivery_signature.strip("|") and delivery_signature != billing_signature
        )

        buyer_note = str(raw.get("buyerNote") or "").strip()

        # Wix order reference stored in customerInternalNote or related fields
        sevdesk_reference = ""
        for ref_key in ("reference", "customerInternalNote", "customerInternalNoteText",
                        "referenceNumber", "orderNumber"):
            val = str(raw.get(ref_key) or "").strip()
            if val:
                sevdesk_reference = val
                break
        order_reference = extract_wix_order_number(sevdesk_reference)

        payload = {
            **raw,
            "id": str(cid) if cid is not None else "",
            "contact_name": contact_name,
            "buyer_note": buyer_note,
            "address_country_code": country_code,
            "delivery_country_code": delivery_country_code,
            "has_delivery_address_override": has_delivery_override,
            "is_sensitive_country": country_code.upper() in DEFAULT_SENSITIVE_COUNTRY_CODES,
            "order_reference": order_reference,
            "sevdesk_reference": sevdesk_reference,
        }
        return cls.model_validate(payload)

    @property
    def formatted_date(self) -> str:
        """Invoice date as DD.MM.YYYY."""
        return _format_date_de(self.invoice_date)

    @property
    def formatted_brutto(self) -> str:
        """Gross amount formatted in German locale (e.g. 1.234,56 €)."""
        return _format_amount_de(self.sum_gross)

    @property
    def formatted_date_short(self) -> str:
        """Invoice date as DD.MM.YY for compact table display."""
        return _format_date_de_short(self.invoice_date)

    def status_label(self) -> str:
        if self.status_code is None:
            return "—"
        return _INVOICE_STATUS_DE.get(self.status_code, str(self.status_code))

    def status_display_label(self) -> str:
        """Return a compact status symbol used by the invoice table."""
        label = self.status_label().casefold()
        if self.status_code == 100:
            return "📝"
        if self.status_code == 200:
            return "🟠"
        if self.status_code == 300:
            return "🟡"
        if self.status_code == 1000:
            return "✅"
        if self.status_code in {1001, 500, 700} or "storn" in label or "cancel" in label:
            return "⛔"
        if self.status_code is None:
            return "—"
        return "•"

    def status_color(self) -> str:
        """Traffic-light color for the invoice table status indicator."""
        label = self.status_label().casefold()
        if self.status_code == 1000:
            return "#22c55e"
        if self.status_code in {200, 300}:
            return "#facc15"
        if self.status_code == 100:
            return "#ef4444"
        if self.status_code in {1001, 500, 700} or "storn" in label or "cancel" in label:
            return "#94a3b8"
        return "#94a3b8"

    @property
    def display_country(self) -> str:
        return self.delivery_country_code or self.address_country_code

    def has_plc_label_candidate(self) -> bool:
        """Detect invoices that likely need PLC label handling."""
        hay = f"{self.order_reference} {self.buyer_note}".strip().lower()
        if not hay:
            return False
        return any(
            token in hay
            for token in (
                "plc",
                "post label center",
                "postlabelcenter",
                "shipping label",
                "versandlabel",
            )
        ) or bool(re.search(r"\bplc[-_ ]?\d+", hay))

    def wix_order_number(self) -> str:
        """Best-effort Wix order number extracted from order reference.

        Never return UUID-like IDs in the dedicated WIX number column.
        """
        return extract_wix_order_number(self.order_reference or self.sevdesk_reference)

    def indicator_icon_keys(self) -> list[str]:
        """Return icon keys used by the hints cell delegate."""
        keys: list[str] = []
        if self.has_unreleased_sku:
            keys.append("print")
        if self.buyer_note.strip():
            keys.append("note")
        if self.has_delivery_address_override:
            keys.append("alternateshippingaddress")
        if self.is_sensitive_country:
            keys.append("country")
        return keys

    def indicator_symbols(self) -> str:
        """Compact marker string for the invoice list."""
        markers: list[str] = []
        if self.has_unreleased_sku:
            markers.append("🖨")
        if self.buyer_note.strip():
            markers.append("✎")
        if self.has_delivery_address_override:
            markers.append("⌂")
        if self.is_sensitive_country:
            markers.append("⚠")
        return " ".join(markers)

    def indicator_tooltip(self) -> str:
        """Detailed explanation for the compact marker cell."""
        lines: list[str] = []
        if self.has_unreleased_sku:
            lines.append("🖨 SKU-Flag aktiv (unreleased/print-relevant)")
        if self.buyer_note.strip():
            lines.append(f"✎ Käufernotiz: {self.buyer_note}")
        if self.has_delivery_address_override:
            lines.append("⌂ Abweichende Lieferanschrift vorhanden")
        if self.is_sensitive_country:
            lines.append(
                f"⚠ Heikles Zielland: {self.address_country_code or self.delivery_country_code or 'unbekannt'}"
            )
        return "\n".join(lines)

    def as_table_row(self) -> dict[str, str]:
        """Keys match German column headers used in :class:`DataTable`."""
        indicator_symbols = self.indicator_symbols()
        icon_keys = self.indicator_icon_keys()

        row: dict[str, str] = {
            "sevDesk": self.invoice_number or "—",
            "WIX": self.wix_order_number() or "—",
            "Datum": self.formatted_date_short,
            _TABLE_STATUS_COLUMN: self.status_display_label(),
            "BETRAG": self.formatted_brutto,
            "Kunde": self.contact_name or "—",
            "Hinweise": indicator_symbols,
            "AKTIONEN": "",
            # Hidden column is also used by text filter; include order ref for Wix-order search.
            "ID": " ".join(
                part
                for part in (self.id, self.order_reference, self.sevdesk_reference)
                if part
            ).strip(),
        }

        row["__align__Hinweise"] = "center"
        row["__align__BETRAG"] = "right"
        row["__icons__Hinweise"] = icon_keys
        row["__plc__enabled"] = True
        row["__has_order_ref__"] = bool(self.order_reference.strip())
        if indicator_symbols:
            row["__tooltip__Hinweise"] = self.indicator_tooltip()
            row["__fg__Hinweise"] = "#ef4444"
        row[f"__tooltip__{_TABLE_STATUS_COLUMN}"] = self.status_label()
        row[f"__align__{_TABLE_STATUS_COLUMN}"] = "center"
        row[f"__status_color__{_TABLE_STATUS_COLUMN}"] = self.status_color()
        row["__tooltip__AKTIONEN"] = "Post Label Center / Wix-Bestellung / Kunden-Mail"
        if self.status_code == 100:
            row[f"__tooltip__{_TABLE_STATUS_COLUMN}"] = "Entwurf: diese Rechnung muss im Tagesgeschäft abgearbeitet werden"
            row[f"__fg__{_TABLE_STATUS_COLUMN}"] = "#9a3412"
            row[f"__bg__{_TABLE_STATUS_COLUMN}"] = "#fff7ed"
        row["__draft_remove_enabled__"] = bool(self.status_code == 100 and not str(self.invoice_number or "").strip())
        if row["__draft_remove_enabled__"]:
            row["__tooltip__sevDesk"] = "Entwurf löschen"

        return row

    def detail_lines(self) -> str:
        """Multi-line description for the detail panel."""
        lines = [
            f"ID: {self.id}",
            f"Nummer: {self.invoice_number or '—'}",
            f"Datum: {self.formatted_date}",
            f"Status: {self.status_label()} ({self.status_code if self.status_code is not None else '—'})",
            f"Brutto: {self.formatted_brutto}",
            f"Kunde: {self.contact_name or '—'}",
            f"Land: {self.display_country or '—'}",
        ]
        if self.has_delivery_address_override:
            lines.append("Lieferanschrift: abweichend")
        if self.delivery_country_code:
            lines.append(f"Lieferland: {self.delivery_country_code}")
        if self.is_sensitive_country:
            lines.append("Achtung: heikles Land")
        if self.buyer_note.strip():
            lines.append(f"Notiz: {self.buyer_note}")
        return "\n".join(lines)


class InvoiceClient:
    """List and fetch invoices from sevDesk."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection
        self._bookkeeping_version: str | None = None

    def list_invoice_summaries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        embed_contact: bool = True,
        status: int | None = None,
    ) -> list[InvoiceSummary]:
        """Return invoice rows (newest first by API default).

        If *status* is set, it is passed to the API as ``status`` (sevDesk may support
        filtering). If the API ignores it, filter client-side.
        """
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if embed_contact:
            params["embed"] = "contact"
        if status is not None:
            params["status"] = status

        response = self._conn.get("/Invoice", params=params)
        payload = response.json()
        objects = payload.get("objects")
        if not isinstance(objects, list):
            logger.warning("Unexpected Invoice list payload: %s", type(objects))
            return []

        result: list[InvoiceSummary] = []
        for obj in objects:
            if isinstance(obj, dict):
                summary = InvoiceSummary.from_api_object(obj)
                if status is not None and summary.status_code != status:
                    continue
                result.append(summary)

        # Keep UI chronology stable: newest sevDesk import first (ID descending).
        result.sort(
            key=lambda item: int(item.id) if item.id.isdigit() else -1,
            reverse=True,
        )

        if status is not None and not result and objects:
            logger.debug(
                "Status filter %s yielded no rows after parse; API may ignore query param.",
                status,
            )
        return result

    def list_invoice_summaries_for_contact(
        self,
        contact_id: str,
        *,
        limit: int = 200,
    ) -> list[InvoiceSummary]:
        """Return invoices linked to one sevDesk contact.

        Used by CRM merge preflight to decide which of a duplicate contact's
        invoices can be safely reassigned before the duplicate is deleted or
        archived.
        """
        params: dict[str, str | int] = {
            "contact[id]": str(contact_id).strip(),
            "contact[objectName]": "Contact",
            "limit": limit,
            "embed": "contact",
        }
        response = self._conn.get("/Invoice", params=params)
        payload = response.json()
        objects = payload.get("objects")
        if not isinstance(objects, list):
            return []
        return [InvoiceSummary.from_api_object(obj) for obj in objects if isinstance(obj, dict)]

    def list_recent_non_draft_summaries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        embed_contact: bool = True,
        excluded_statuses: set[int] | None = None,
    ) -> list[InvoiceSummary]:
        """Return newest invoices excluding drafts, with offset in filtered space."""
        excluded = set(excluded_statuses or {100})
        target_skip = max(0, int(offset))
        target_limit = max(1, int(limit))
        raw_offset = 0
        page_size = max(target_limit, 100)
        skipped = 0
        result: list[InvoiceSummary] = []

        while len(result) < target_limit:
            batch = self.list_invoice_summaries(
                limit=page_size,
                offset=raw_offset,
                embed_contact=embed_contact,
                status=None,
            )
            if not batch:
                break
            raw_offset += len(batch)

            for summary in batch:
                if summary.status_code in excluded:
                    continue
                if skipped < target_skip:
                    skipped += 1
                    continue
                result.append(summary)
                if len(result) >= target_limit:
                    break

            if len(batch) < page_size:
                break

        return result

    def search_invoice_summaries(
        self,
        query: str,
        *,
        initial_window_days: int = 100,
        window_step_days: int = 100,
        limit_per_page: int = 200,
        max_windows: int = 20,
    ) -> tuple[list[InvoiceSummary], int]:
        """Search sevDesk invoices by reference/customer/invoice number with widening date windows.

        The search starts with the newest *initial_window_days* and automatically expands by
        *window_step_days* until matches are found or the invoice history is exhausted.
        Returns ``(matches, searched_days)``.
        """
        needle = self._normalize_search_text(query)
        if not needle:
            return [], max(1, int(initial_window_days))

        searched_days = max(1, int(initial_window_days))
        today = date.today()
        fetched: list[InvoiceSummary] = []
        offset = 0
        reached_end = False

        while searched_days <= max(1, int(initial_window_days)) + max(0, int(window_step_days)) * max(0, int(max_windows) - 1):
            oldest_age = self._oldest_fetched_age_days(fetched, today) if fetched else 0
            cutoff_reached = oldest_age >= searched_days if fetched else False
            while not reached_end and not cutoff_reached:
                batch = self.list_invoice_summaries(limit=limit_per_page, offset=offset, status=None)
                if not batch:
                    reached_end = True
                    break
                fetched.extend(batch)
                offset += len(batch)
                if len(batch) < limit_per_page:
                    reached_end = True
                oldest_age = self._oldest_fetched_age_days(fetched, today)
                cutoff_reached = oldest_age >= searched_days

            matches = [
                summary for summary in fetched
                if self._within_days(summary, today, searched_days) and self._matches_search_query(summary, needle)
            ]
            if matches:
                matches.sort(
                    key=lambda item: int(item.id) if item.id.isdigit() else -1,
                    reverse=True,
                )
                return matches, searched_days
            if reached_end and oldest_age <= searched_days:
                return [], searched_days
            searched_days += max(1, int(window_step_days))

        return [], searched_days

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        text = str(value or "").strip().casefold()
        text = (
            text.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        text = "".join(
            ch for ch in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(ch)
        )
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @classmethod
    def _matches_search_query(cls, summary: InvoiceSummary, needle: str) -> bool:
        order_ref = str(summary.order_reference or "").strip()
        sevdesk_ref = str(summary.sevdesk_reference or "").strip()
        haystacks = [
            cls._normalize_search_text(summary.invoice_number),
            cls._normalize_search_text(summary.contact_name),
            cls._normalize_search_text(order_ref),
            cls._normalize_search_text(sevdesk_ref),
        ]
        if any(needle and needle in hay for hay in haystacks if hay):
            return True
        tokens = [token for token in needle.split() if token]
        if not tokens:
            return False
        combined = " ".join(hay for hay in haystacks if hay)
        return all(token in combined for token in tokens)

    @staticmethod
    def _parse_invoice_date(value: str | None) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).date()
        except (TypeError, ValueError):
            return None

    @classmethod
    def _within_days(cls, summary: InvoiceSummary, today: date, days: int) -> bool:
        dt = cls._parse_invoice_date(summary.invoice_date)
        if dt is None:
            return True
        return (today - dt).days <= days

    @classmethod
    def _oldest_fetched_age_days(cls, rows: list[InvoiceSummary], today: date) -> int:
        ages: list[int] = []
        for summary in rows:
            dt = cls._parse_invoice_date(summary.invoice_date)
            if dt is None:
                continue
            ages.append((today - dt).days)
        return max(ages, default=0)

    def fetch_invoice_by_id(self, invoice_id: str) -> dict[str, Any]:
        """Return one invoice object as returned by sevDesk."""
        response = self._conn.get(f"/Invoice/{str(invoice_id).strip()}")
        payload = response.json()
        if isinstance(payload, dict):
            objects = payload.get("objects")
            if isinstance(objects, list):
                for item in objects:
                    if isinstance(item, dict):
                        return item
            if isinstance(objects, dict):
                return objects
            return payload
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    return item
        return {}

    @staticmethod
    def invoice_reference(invoice: dict[str, Any]) -> str:
        for ref_key in (
            "reference",
            "customerInternalNote",
            "customerInternalNoteText",
            "referenceNumber",
            "orderNumber",
        ):
            value = str(invoice.get(ref_key) or "").strip()
            if value:
                return value
        return ""

    def get_check_account_id_by_name(
        self,
        name: str,
        *,
        preferred_types: tuple[str, ...] = (),
    ) -> int | None:
        response = self._conn.get("/CheckAccount", params={"limit": 500, "offset": 0})
        payload = response.json()
        objects = payload.get("objects") if isinstance(payload, dict) else []
        if not isinstance(objects, list):
            return None
        wanted = str(name or "").strip().casefold()
        preferred = {str(item or "").strip().casefold() for item in preferred_types if str(item or "").strip()}
        fallback_id: int | None = None
        for raw in objects:
            if not isinstance(raw, dict):
                continue
            account_name = str(raw.get("name") or "").strip().casefold()
            if account_name != wanted:
                continue
            raw_id = raw.get("id")
            try:
                parsed_id = int(str(raw_id))
            except (TypeError, ValueError):
                continue
            account_type = str(raw.get("type") or "").strip().casefold()
            if preferred and account_type in preferred:
                return parsed_id
            if fallback_id is None:
                fallback_id = parsed_id
        return fallback_id

    def get_invoice_check_account_transactions(self, invoice_id: int) -> list[dict[str, Any]]:
        response = self._conn.get(f"/Invoice/{int(invoice_id)}/getCheckAccountTransactions")
        payload = response.json() if response.content else {}
        if isinstance(payload, dict):
            objects = payload.get("objects", payload.get("data", []))
            if isinstance(objects, dict):
                return [objects]
            if isinstance(objects, list):
                return [item for item in objects if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def find_check_account_transactions(
        self,
        check_account_id: int,
        *,
        purpose: str = "",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, object] = {
            "checkAccount[id]": int(check_account_id),
            "checkAccount[objectName]": "CheckAccount",
            "limit": 500,
            "offset": 0,
        }
        if start_date is not None:
            params["startDate"] = start_date.astimezone(timezone.utc).isoformat()
        if end_date is not None:
            params["endDate"] = end_date.astimezone(timezone.utc).isoformat()
        response = self._conn.get("/CheckAccountTransaction", params=params)
        payload = response.json() if response.content else {}
        objects = payload.get("objects") if isinstance(payload, dict) else []
        if not isinstance(objects, list):
            return []
        exact_purpose = str(purpose or "").strip().casefold()
        out = [item for item in objects if isinstance(item, dict)]
        if not exact_purpose:
            return out
        return [
            item
            for item in out
            if str(item.get("paymtPurpose") or "").strip().casefold() == exact_purpose
        ]

    def create_check_account_transaction(
        self,
        check_account_id: int,
        amount: float,
        *,
        value_date: datetime,
        payee: str,
        purpose: str,
    ) -> int:
        iso_value_date = value_date.astimezone(timezone.utc).isoformat()
        payload = {
            "valueDate": iso_value_date,
            "entryDate": iso_value_date,
            "checkAccount": {"id": int(check_account_id), "objectName": "CheckAccount"},
            "amount": float(amount),
            "status": 100,
            "payeePayerName": str(payee or "").strip(),
            "paymtPurpose": str(purpose or "").strip(),
        }
        response = self._conn.post("/CheckAccountTransaction", json=payload)
        payload = response.json() if response.content else {}
        objects = payload.get("objects") if isinstance(payload, dict) else []
        if isinstance(objects, dict):
            objects = [objects]
        if isinstance(objects, list):
            for item in objects:
                if not isinstance(item, dict):
                    continue
                try:
                    return int(str(item.get("id")))
                except (TypeError, ValueError):
                    continue
        raise RuntimeError("sevDesk lieferte keine Transaktions-ID")

    @staticmethod
    def _is_paid_invoice_object(invoice: dict[str, Any]) -> bool:
        return is_paid_invoice_object(invoice)

    def get_check_account_transaction_by_id(self, transaction_id: int) -> dict[str, Any]:
        response = self._conn.get(f"/CheckAccountTransaction/{int(transaction_id)}")
        payload = response.json() if response.content else {}
        if isinstance(payload, dict):
            objects = payload.get("objects", payload)
            if isinstance(objects, list):
                return next((item for item in objects if isinstance(item, dict)), {})
            if isinstance(objects, dict):
                return objects
        if isinstance(payload, list):
            return next((item for item in payload if isinstance(item, dict)), {})
        return {}

    def change_check_account_transaction_status(self, transaction_id: int, status: int) -> dict[str, Any]:
        response = self._conn.put(
            f"/CheckAccountTransaction/{int(transaction_id)}",
            json={"status": int(status)},
        )
        return response.json() if response.content else {}

    def book_invoice_with_transaction(
        self,
        invoice_id: int,
        amount: float,
        *,
        check_account_id: int,
        transaction_id: int,
        booking_date: int,
    ) -> dict[str, Any]:
        invoice_before = self.fetch_invoice_by_id(str(invoice_id))
        if self._is_paid_invoice_object(invoice_before):
            return {
                "status": "invoice_already_paid",
                "transaction_id": int(transaction_id),
                "invoice_status": str(invoice_before.get("status") or "").strip(),
            }

        tx_before = self.get_check_account_transaction_by_id(int(transaction_id))
        tx_status_before = str(tx_before.get("status") or "").strip()
        if tx_status_before == "400":
            return {
                "status": "already_booked",
                "transaction_id": int(transaction_id),
                "tx_status": tx_status_before,
            }

        tx_account_id = str((tx_before.get("checkAccount") or {}).get("id") or "").strip()
        if tx_account_id and tx_account_id != str(int(check_account_id)):
            return {
                "status": "account_mismatch",
                "transaction_id": int(transaction_id),
                "tx_account_id": tx_account_id,
                "check_account_id": str(int(check_account_id)),
            }

        if self._bookkeeping_system_version() == "1.0":
            self._legacy_link_invoice(
                transaction_id=int(transaction_id),
                invoice_id=int(invoice_id),
                amount=amount,
                booking_date=int(booking_date),
            )
        else:
            response = self._conn.put(
                f"/Invoice/{int(invoice_id)}/bookAmount",
                json=book_amount_payload(
                    amount=amount,
                    booking_date=int(booking_date),
                    check_account_id=int(check_account_id),
                    transaction_id=int(transaction_id),
                ),
            )
            payload = response_payload(response)
            raise_on_error_envelope(payload, "sevDesk Invoice bookAmount Fehler")

        invoice_after = self.fetch_invoice_by_id(str(invoice_id))
        tx_after = self.get_check_account_transaction_by_id(int(transaction_id))
        tx_status_after = str(tx_after.get("status") or "").strip()

        if not self._is_paid_invoice_object(invoice_after):
            return {
                "status": "not_booked",
                "transaction_id": int(transaction_id),
                "invoice_status": str(invoice_after.get("status") or "").strip(),
                "tx_status": tx_status_after,
            }

        if tx_status_after != "400":
            try:
                self.change_check_account_transaction_status(int(transaction_id), 400)
                tx_after = self.get_check_account_transaction_by_id(int(transaction_id))
                tx_status_after = str(tx_after.get("status") or "").strip()
            except Exception:
                pass

        return {
            "status": "booked",
            "transaction_id": int(transaction_id),
            "invoice_status": str(invoice_after.get("status") or "").strip(),
            "tx_status": tx_status_after,
        }

    def _legacy_link_invoice(
        self,
        *,
        transaction_id: int,
        invoice_id: int,
        amount: float,
        booking_date: int,
    ) -> dict[str, Any]:
        params = {"invoiceId": int(invoice_id)}
        body = {
            "amount": normalize_booking_amount(amount),
            "date": int(booking_date),
        }
        last_exc: Exception | None = None
        for method in ("put", "patch"):
            try:
                request = self._conn.put if method == "put" else self._conn.patch
                response = request(
                    f"/CheckAccountTransaction/{int(transaction_id)}/linkInvoice",
                    params=params,
                    json=body,
                )
                payload = response_payload(response)
                raise_on_error_envelope(payload, "sevDesk linkInvoice Fehler")
                return payload
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"sevDesk linkInvoice Fehler: {last_exc}")

    def _bookkeeping_system_version(self) -> str:
        if self._bookkeeping_version:
            return self._bookkeeping_version
        try:
            response = self._conn.get("/Tools/bookkeepingSystemVersion")
            payload = response.json()
            obj = payload.get("objects", payload) if isinstance(payload, dict) else {}
            if isinstance(obj, list):
                obj = obj[0] if obj else {}
            version = str(obj.get("version") or "") if isinstance(obj, dict) else ""
        except Exception:
            version = "1.0"
        self._bookkeeping_version = version or "1.0"
        return self._bookkeeping_version

    def fetch_invoice_positions(self, invoice_id: str) -> list[dict[str, Any]]:
        """Return invoice positions for one invoice."""
        params = {
            "invoice[id]": str(invoice_id).strip(),
            "invoice[objectName]": "Invoice",
            "embed": "part",
        }
        response = self._conn.get("/InvoicePos", params=params)
        payload = response.json()
        objects = payload.get("objects") if isinstance(payload, dict) else []
        if not isinstance(objects, list):
            return []
        return [item for item in objects if isinstance(item, dict)]

    def update_invoice_draft(
        self,
        invoice: dict[str, Any],
        positions: list[dict[str, Any]],
        *,
        take_default_address: bool = False,
    ) -> dict[str, Any]:
        """Persist a modified draft invoice with normalized positions."""
        payload = {
            "invoice": self._normalize_invoice_for_save(invoice),
            "invoicePosSave": [self._normalize_invoice_position_for_save(position) for position in positions or []],
            "invoicePosDelete": None,
            "discountSave": [],
            "discountDelete": None,
            "takeDefaultAddress": bool(take_default_address),
        }
        response = self._conn.post("/Invoice/Factory/saveInvoice", json=payload)
        return response.json() if response.content else {}

    def delete_draft_invoice(self, invoice_id: str) -> None:
        """Delete one draft invoice by id."""
        self._conn.delete(f"/Invoice/{str(invoice_id).strip()}")

    def send_invoice_document(
        self,
        invoice_id: str,
        *,
        send_type: str = "VPR",
        send_draft: bool = False,
    ) -> dict[str, Any]:
        """Trigger sevDesk ``sendBy`` for one invoice."""
        body = {
            "sendType": str(send_type).strip() or "VPR",
            "sendDraft": bool(send_draft),
        }
        response = self._conn.put(f"/Invoice/{str(invoice_id).strip()}/sendBy", json=body)
        return response.json() if response.content else {}

    def send_invoice_via_email(
        self,
        invoice_id: str,
        *,
        to_email: str,
        subject: str,
        text: str,
        copy: bool = True,
        cc_email: str = "",
        bcc_email: str = "",
    ) -> dict[str, Any]:
        """Send one invoice via sevDesk email delivery."""
        body = {
            "toEmail": str(to_email or "").strip(),
            "subject": str(subject or "").strip(),
            "text": str(text or "").strip(),
            "copy": bool(copy),
        }
        if str(cc_email or "").strip():
            body["ccEmail"] = str(cc_email).strip()
        if str(bcc_email or "").strip():
            body["bccEmail"] = str(bcc_email).strip()
        response = self._conn.post(f"/Invoice/{str(invoice_id).strip()}/sendViaEmail", json=body)
        return response.json() if response.content else {}

    def render_invoice_pdf(self, invoice_id: str) -> dict[str, Any]:
        """Ask sevDesk to render invoice PDF asynchronously."""
        response = self._conn.post(
            f"/Invoice/{str(invoice_id).strip()}/render",
            json={},
            params={"getAsPdf": "true"},
        )
        return response.json() if response.content else {}

    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        """Load rendered invoice PDF bytes from sevDesk."""
        response = self._conn.get(
            f"/Invoice/{str(invoice_id).strip()}/getPdf",
            params={"download": "true", "preventSendBy": "true"},
            headers={"Accept": "application/pdf,application/json"},
        )
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if response.content and response.content.startswith(b"%PDF"):
            return response.content

        payload: Any
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"sevDesk PDF: ungültige Antwort (content-type={content_type})"
            ) from exc

        decoded = self.extract_pdf_from_payload(payload)
        if decoded:
            return decoded
        raise ValueError("sevDesk PDF: kein PDF/base64 geliefert")

    def _normalize_invoice_for_save(self, invoice: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(invoice, dict):
            raise RuntimeError("Invoice-Payload fuer saveInvoice ist ungueltig")
        payload: dict[str, Any] = {
            "id": str(invoice.get("id") or "").strip(),
            "objectName": "Invoice",
            "mapAll": True,
        }
        for key in (
            "invoiceDate",
            "deliveryDate",
            "status",
            "invoiceType",
            "currency",
            "discount",
            "address",
            "taxRate",
            "taxType",
            "taxText",
            "customerInternalNote",
            "showNet",
            "invoiceNumber",
            "header",
            "headText",
            "footText",
            "timeToPay",
        ):
            if key in invoice and invoice.get(key) not in (None, ""):
                payload[key] = invoice.get(key)
        for key, object_name in (
            ("contact", "Contact"),
            ("contactPerson", "SevUser"),
            ("addressCountry", "StaticCountry"),
            ("paymentMethod", "PaymentMethod"),
            ("taxRule", "TaxRule"),
        ):
            ref = self._normalize_ref(invoice.get(key), object_name)
            if ref:
                payload[key] = ref
        return payload

    def _normalize_invoice_position_for_save(self, position: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(position, dict):
            raise RuntimeError("InvoicePos-Payload fuer saveInvoice ist ungueltig")
        payload: dict[str, Any] = {
            "id": str(position.get("id") or "").strip(),
            "objectName": "InvoicePos",
            "mapAll": True,
            "name": str(position.get("name") or "").strip() or "Position",
            "text": str(position.get("text") or "").strip(),
            "quantity": self._to_float_scalar(position.get("quantity") or 1),
            "price": self._to_float_scalar(
                position.get("price") if position.get("price") not in (None, "") else position.get("priceNet")
            ),
            "taxRate": self._to_float_scalar(position.get("taxRate")),
            "positionNumber": self._to_int_scalar(position.get("positionNumber")),
        }
        unity = self._normalize_ref(position.get("unity"), "Unity")
        if unity:
            payload["unity"] = unity
        part = self._normalize_ref(position.get("part"), "Part")
        if part:
            payload["part"] = part
        discount = position.get("discount")
        if discount not in (None, "", 0, 0.0):
            payload["discount"] = self._to_float_scalar(discount)
            payload["isPercentage"] = bool(position.get("isPercentage"))
        return payload

    @staticmethod
    def _normalize_ref(value: Any, object_name: str) -> dict[str, str] | None:
        if isinstance(value, dict):
            ref_id = str(value.get("id") or "").strip()
            if ref_id:
                return {"id": ref_id, "objectName": object_name}
        else:
            ref_id = str(value or "").strip()
            if ref_id:
                return {"id": ref_id, "objectName": object_name}
        return None

    @staticmethod
    def _to_float_scalar(value: Any) -> float:
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return 0.0

    @staticmethod
    def _to_int_scalar(value: Any) -> int:
        try:
            return int(float(str(value).strip()))
        except Exception:
            return 0

    def extract_pdf_from_payload(self, payload: object) -> bytes | None:
        """Extract PDF bytes from sevDesk render/getPdf JSON payloads."""
        return self._extract_pdf_from_payload(payload)

    def _extract_pdf_from_payload(self, payload: object) -> bytes | None:
        if not isinstance(payload, dict):
            return None
        for key in ("pdf", "base64", "pdfBase64", "documentBase64"):
            raw = payload.get(key)
            if not raw:
                continue
            try:
                encoded = str(raw).strip()
                if encoded.lower().startswith("data:application/pdf;base64,"):
                    encoded = encoded.split(",", 1)[1]
                decoded = base64.b64decode(encoded, validate=False)
            except Exception:
                continue
            if decoded.startswith(b"%PDF"):
                return decoded
        response_block = payload.get("response")
        if isinstance(response_block, dict):
            decoded = self._extract_pdf_from_payload(response_block)
            if decoded:
                return decoded
        objects = payload.get("objects")
        if isinstance(objects, dict):
            decoded = self._extract_pdf_from_payload(objects)
            if decoded:
                return decoded
        if isinstance(objects, list):
            for item in objects:
                decoded = self._extract_pdf_from_payload(item)
                if decoded:
                    return decoded
        return None
