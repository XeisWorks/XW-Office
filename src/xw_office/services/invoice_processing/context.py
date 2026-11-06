"""Source-neutral working context for sevDesk invoices.

The Rechnungen UI historically treated a Wix order as the source of truth for
customer, address and product data.  This module keeps the same data contract
for Wix invoices while also allowing a manually-created sevDesk draft to be
processed from the sevDesk invoice and InvoicePos resources alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Literal

from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.shipping.countries import country_label_for_address

InvoiceOrigin = Literal["sevdesk_only", "wix_candidate", "wix_confirmed"]
PositionKind = Literal["product", "shipping", "service", "discount", "unknown"]

_SKU_RE = re.compile(r"\bXW-[A-Z0-9][A-Z0-9._-]*\b", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"^(?:versand|versandkosten|shipping|porto|fracht)(?:\s|$)", re.I)
_DISCOUNT_RE = re.compile(r"(?:rabatt|discount|gutschrift|nachlass)", re.I)


@dataclass(frozen=True)
class InvoiceWorkPosition:
    """Normalized sevDesk invoice position used by detail, PLC and printing."""

    source_id: str
    position_number: int
    part_id: str
    sku: str
    sku_source: str
    name: str
    description: str
    quantity: Decimal
    kind: PositionKind
    printable: bool
    unit_weight_kg: float | None = None
    unit_value: Decimal | None = None
    currency: str = "EUR"
    warnings: tuple[str, ...] = ()

    @property
    def quantity_is_integer(self) -> bool:
        return self.quantity == self.quantity.to_integral_value()

    @property
    def quantity_int(self) -> int:
        return max(0, int(self.quantity))


@dataclass(frozen=True)
class InvoiceCapabilities:
    """Actions available for the currently resolved invoice context."""

    has_wix_order: bool = False
    has_customer_email: bool = False
    has_shipping_address: bool = False
    has_invoice_pdf: bool = True
    has_product_positions: bool = False
    has_printable_products: bool = False
    can_print_address_label: bool = False
    can_create_plc_label: bool = False
    can_create_customs_document: bool = False
    can_send_invoice: bool = False


@dataclass(frozen=True)
class InvoiceWorkContext:
    """Complete, source-neutral context for one invoice."""

    summary: InvoiceSummary
    origin: InvoiceOrigin
    wix_order_number_candidate: str = ""
    confirmed_wix_order_number: str = ""
    customer_name: str = ""
    customer_email: str = ""
    billing_address_lines: tuple[str, ...] = ()
    shipping_address_lines: tuple[str, ...] = ()
    shipping_address_source: str = ""
    positions: tuple[InvoiceWorkPosition, ...] = ()
    capabilities: InvoiceCapabilities = field(default_factory=InvoiceCapabilities)
    warnings: tuple[str, ...] = ()
    source_updated_at: str = ""

    @property
    def wix_order_number(self) -> str:
        return self.confirmed_wix_order_number

    @property
    def invoice_reference(self) -> str:
        return str(self.summary.invoice_number or "").strip() or f"SEVDESK-{self.summary.id}"

    @property
    def is_sevdesk_only(self) -> bool:
        return self.origin == "sevdesk_only"


def decimal_value(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return default
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default


def _text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("original", "translated", "value", "name", "text", "label"):
            result = _text(value.get(key))
            if result:
                return result
        return ""
    return str(value or "").strip()


def _part_object(raw: dict[str, Any]) -> dict[str, Any]:
    part = raw.get("part")
    return part if isinstance(part, dict) else {}


def normalize_invoice_positions(
    raw_positions: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> tuple[InvoiceWorkPosition, ...]:
    """Normalize sevDesk InvoicePos payloads without inventing product data."""

    result: list[InvoiceWorkPosition] = []
    for index, raw in enumerate(raw_positions or []):
        if not isinstance(raw, dict):
            continue
        part = _part_object(raw)
        part_id = _text(part.get("id") or raw.get("partId"))
        sku = _text(
            part.get("partNumber")
            or part.get("partnumber")
            or part.get("sku")
            or raw.get("sku")
        ).upper()
        sku_source = "part" if sku and part else ("position" if sku else "")
        if not sku:
            candidate = _SKU_RE.search(_text(raw.get("text")))
            if candidate:
                sku = candidate.group(0).upper()
                sku_source = "text"

        name = _text(raw.get("name") or part.get("name") or raw.get("text"))
        description = _text(raw.get("text") or part.get("text"))
        quantity = decimal_value(raw.get("quantity") or raw.get("qty"), Decimal("1"))
        position_number_raw = raw.get("positionNumber")
        try:
            position_number = int(position_number_raw) if position_number_raw is not None else index
        except (TypeError, ValueError):
            position_number = index

        has_part = bool(part_id or sku)
        if _DISCOUNT_RE.search(name or description) or quantity < 0:
            kind: PositionKind = "discount"
        elif not has_part and _SHIPPING_RE.search(name):
            kind = "shipping"
        elif has_part:
            kind = "product"
        elif name:
            kind = "service"
        else:
            kind = "unknown"

        warnings: list[str] = []
        printable = kind == "product" and quantity > 0 and quantity == quantity.to_integral_value()
        if kind == "product" and not sku:
            warnings.append("Keine SKU/Part-Zuordnung")
            printable = False
        if kind == "product" and quantity != quantity.to_integral_value():
            warnings.append("Bruchmenge ist nicht druckbar")
            printable = False
        if kind in {"service", "unknown"}:
            warnings.append("Keine physische Produktposition")

        unit_value = decimal_value(raw.get("priceGross") or raw.get("price"), Decimal("0"))
        result.append(
            InvoiceWorkPosition(
                source_id=_text(raw.get("id")) or f"position-{index}",
                position_number=position_number,
                part_id=part_id,
                sku=sku,
                sku_source=sku_source,
                name=name or sku or "Unbenannte Position",
                description=description,
                quantity=quantity,
                kind=kind,
                printable=printable,
                unit_value=unit_value,
                warnings=tuple(warnings),
            )
        )
    result.sort(key=lambda item: (item.position_number, item.source_id))
    return tuple(result)


def normalize_address_lines(value: object) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.replace("\r", "").split("\n") if line.strip()]
    if isinstance(value, (list, tuple)):
        return [str(line).strip() for line in value if str(line).strip()]
    return []


def address_lines_from_invoice(invoice: dict[str, Any], summary: InvoiceSummary) -> tuple[
    tuple[str, ...], tuple[str, ...], str
]:
    """Return billing, shipping and source without mutating sevDesk."""

    contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
    def first(*values: object) -> str:
        for value in values:
            text = _text(value)
            if text:
                return text
        return ""

    billing_name = first(invoice.get("addressName"), invoice.get("name"), contact.get("name"), summary.contact_name)
    billing_street = first(invoice.get("addressStreet"), invoice.get("street"))
    billing_city = first(
        " ".join(part for part in (invoice.get("addressZip"), invoice.get("addressCity")) if _text(part)),
        " ".join(part for part in (invoice.get("zip"), invoice.get("city")) if _text(part)),
    )
    billing_country = first(invoice.get("addressCountryCode"), invoice.get("addressCountry"), summary.display_country)
    billing_country = country_label_for_address(billing_country) if billing_country else ""
    billing = [line for line in (billing_name, billing_street, billing_city, billing_country) if line]
    if not billing:
        billing = normalize_address_lines(invoice.get("address"))
        if billing and billing_country and billing[-1].casefold() != billing_country.casefold():
            billing.append(billing_country)

    shipping_obj = invoice.get("shippingAddress")
    if not isinstance(shipping_obj, dict):
        shipping_obj = invoice.get("deliveryAddress") if isinstance(invoice.get("deliveryAddress"), dict) else {}
    shipping_name = first(invoice.get("deliveryName"), invoice.get("shippingName"), shipping_obj.get("name"))
    shipping_street = first(
        invoice.get("deliveryStreet"), invoice.get("shippingStreet"), shipping_obj.get("street"), shipping_obj.get("addressLine1")
    )
    shipping_city = first(
        " ".join(part for part in (invoice.get("deliveryZip"), invoice.get("deliveryCity")) if _text(part)),
        " ".join(part for part in (invoice.get("shippingZip"), invoice.get("shippingCity")) if _text(part)),
        " ".join(part for part in (shipping_obj.get("postalCode"), shipping_obj.get("city")) if _text(part)),
    )
    shipping_country = first(
        invoice.get("deliveryCountry"), invoice.get("deliveryAddressCountry"), invoice.get("shippingCountry"), shipping_obj.get("country")
    )
    shipping_country = country_label_for_address(shipping_country) if shipping_country else ""
    shipping = [line for line in (shipping_name, shipping_street, shipping_city, shipping_country) if line]
    if not shipping and isinstance(invoice.get("deliveryAddress"), str):
        shipping = normalize_address_lines(invoice.get("deliveryAddress"))

    if len(shipping) >= 2:
        return tuple(billing), tuple(shipping), "sevdesk_delivery"
    if billing:
        return tuple(billing), tuple(billing), "billing_fallback"
    return (), (), ""


def build_capabilities(
    *,
    customer_email: str,
    shipping_lines: tuple[str, ...],
    positions: tuple[InvoiceWorkPosition, ...],
    has_wix_order: bool = False,
) -> InvoiceCapabilities:
    printable = any(position.printable for position in positions)
    return InvoiceCapabilities(
        has_wix_order=has_wix_order,
        has_customer_email=bool(customer_email.strip()),
        has_shipping_address=len(shipping_lines) >= 2,
        has_product_positions=any(position.kind == "product" for position in positions),
        has_printable_products=printable,
        can_print_address_label=len(shipping_lines) >= 2,
        can_create_plc_label=len(shipping_lines) >= 2,
        can_create_customs_document=len(shipping_lines) >= 2,
        can_send_invoice=bool(customer_email.strip()),
    )
