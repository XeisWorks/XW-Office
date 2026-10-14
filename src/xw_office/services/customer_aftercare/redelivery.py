"""Invoice-driven redelivery preparation.

This module deliberately performs only deterministic enrichment. OpenAI may
later turn the returned context into a note, but it is never used as the
source of truth for customer, address, SKU or quantity.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Sequence

from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.repositories.customer_aftercare import (
    CustomerAftercareItemInput,
    CustomerAftercareRepository,
    CustomerAftercareReservation,
)
from xw_office.services.customer_aftercare.ai_classifier import classify_mail
from xw_office.services.secrets.service import SecretService
from xw_office.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.wix.client import WixOrdersClient


@dataclass(frozen=True)
class RedeliveryContext:
    reservation: CustomerAftercareReservation
    case: CustomerAftercareCase
    items: tuple[CustomerAftercareItem, ...]
    address_lines: tuple[str, ...]
    address_source: str
    wix_contact_id: str
    sevdesk_contact_id: str
    customer_email: str


class CustomerAftercareRedeliveryService:
    """Create and enrich an editable case from one sevDesk invoice."""

    def __init__(
        self,
        repo: CustomerAftercareRepository | None,
        invoices: InvoiceClient | None,
        wix_orders: WixOrdersClient | None,
        secrets: SecretService | None = None,
        product_catalog: ProductCatalogService | None = None,
    ) -> None:
        self._repo = repo
        self._invoices = invoices
        self._wix_orders = wix_orders
        self._secrets = secrets
        self._product_catalog = product_catalog

    def prepare_from_invoice(self, summary: InvoiceSummary) -> RedeliveryContext:
        if self._repo is None:
            raise RuntimeError("Nachlieferungen benötigen eine konfigurierte Datenbank")
        invoice_id = str(summary.id or "").strip()
        invoice_number = str(summary.invoice_number or "").strip()
        raw_invoice: dict[str, Any] = {}
        if self._invoices is not None and invoice_id:
            payload = self._invoices.fetch_invoice_by_id(invoice_id)
            if isinstance(payload, dict):
                raw_invoice = payload
        if not invoice_number:
            invoice_number = str(
                raw_invoice.get("invoiceNumber") or raw_invoice.get("number") or ""
            ).strip()

        contact = raw_invoice.get("contact") if isinstance(raw_invoice.get("contact"), dict) else {}
        sevdesk_contact_id = str(contact.get("id") or raw_invoice.get("contactId") or "").strip()
        order_number = str(summary.order_reference or "").strip()
        if not order_number:
            order_number = self._extract_order_number(raw_invoice)
        order: dict[str, Any] = {}
        if self._wix_orders is not None and order_number:
            try:
                resolved = self._wix_orders.resolve_order(order_number)
                order = resolved if isinstance(resolved, dict) else {}
            except Exception:
                order = {}

        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        wix_contact_id = str(buyer.get("contactId") or "").strip()
        email = str(
            buyer.get("email")
            or (buyer.get("contact") or {}).get("email")
            if isinstance(buyer.get("contact"), dict)
            else buyer.get("email")
            or ""
        ).strip()
        customer_email = email or self._invoice_email(raw_invoice)
        address_lines: list[str] = []
        address_source = ""
        if order and self._wix_orders is not None:
            address_lines = self._wix_orders.best_address_lines_from_order(order)
            if address_lines:
                address_source = "wix"
        if not address_lines:
            address_lines = self._invoice_address_lines(raw_invoice)
            if address_lines:
                address_source = "sevdesk"

        wix_order_id = str(order.get("id") or "").strip()
        items = self._invoice_items(invoice_id, invoice_number, order_number)
        note = (
            f"Nachlieferung zu {invoice_number or invoice_id}"
            + (f" / Wix {order_number}" if order_number else "")
        )
        ai_payload_json = ""
        api_key = self._secrets.get_secret("OPENAI_API_KEY") if self._secrets is not None else ""
        if api_key:
            ai = classify_mail(
                subject=f"Nachlieferung zu {invoice_number or invoice_id}",
                sender=customer_email,
                body_text=(
                    f"Kunde: {summary.contact_name}\nAdresse: {' | '.join(address_lines)}\n"
                    f"Produkte: {', '.join(f'{item.quantity}x {item.name or item.sku}' for item in items)}"
                ),
                api_key=api_key,
            )
            if ai.source == "openai" and ai.note:
                note = ai.note
                ai_payload_json = ai.to_payload_json()
        reservation = self._repo.create_invoice_case(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            order_number=order_number,
            wix_order_id=wix_order_id,
            customer_name=str(summary.contact_name or "").strip(),
            customer_email=customer_email,
            sevdesk_contact_id=sevdesk_contact_id,
            wix_contact_id=wix_contact_id,
            address_lines=address_lines,
            address_source=address_source,
            items=items,
            note=note,
            ai_payload_json=ai_payload_json,
        )
        case = self._repo.get_case(reservation.case.id) or reservation.case
        stored_items = tuple(self._repo.get_items(case.id))
        return RedeliveryContext(
            reservation=reservation,
            case=case,
            items=stored_items,
            address_lines=tuple(address_lines),
            address_source=address_source,
            wix_contact_id=wix_contact_id,
            sevdesk_contact_id=sevdesk_contact_id,
            customer_email=customer_email,
        )

    def _invoice_items(
        self, invoice_id: str, invoice_number: str, order_number: str
    ) -> list[CustomerAftercareItemInput]:
        if self._invoices is None or not invoice_id:
            return []
        try:
            positions = self._invoices.fetch_invoice_positions(invoice_id)
        except Exception:
            return []
        items: list[CustomerAftercareItemInput] = []
        for index, position in enumerate(positions):
            if not isinstance(position, dict):
                continue
            part = position.get("part") if isinstance(position.get("part"), dict) else {}
            name = str(
                position.get("name")
                or position.get("text")
                or part.get("name")
                or part.get("text")
                or ""
            ).strip()
            sku = str(position.get("sku") or part.get("sku") or "").strip()
            if not name and not sku:
                continue
            try:
                quantity = max(1, int(float(position.get("quantity") or position.get("qty") or 1)))
            except (TypeError, ValueError):
                quantity = 1
            components = position.get("components")
            if not components and self._product_catalog is not None and sku:
                components = self._product_catalog.resolve_components(sku)
            if isinstance(components, list) and components:
                for component_index, component in enumerate(components):
                    if not isinstance(component, dict):
                        continue
                    component_name = str(
                        component.get("name") or component.get("title") or component.get("label") or ""
                    ).strip()
                    component_sku = str(component.get("sku") or component.get("id") or "").strip()
                    if not component_name and not component_sku:
                        continue
                    try:
                        component_quantity = max(
                            1,
                            int(float(component.get("quantity") or component.get("qty") or quantity)),
                        )
                    except (TypeError, ValueError):
                        component_quantity = quantity
                    items.append(
                        CustomerAftercareItemInput(
                            role="MISSING_TO_SEND",
                            sku=component_sku,
                            name=component_name or component_sku,
                            quantity=component_quantity,
                            sevdesk_part_id=str(part.get("id") or "").strip(),
                            source_unit_price=_decimal_or_none(component.get("price")),
                            source_tax_rate=_decimal_or_none(component.get("taxRate")),
                            source_discount_percent=_decimal_or_none(component.get("discount")),
                            source_kind="product_hub_component",
                            source_item_id=str(component.get("id") or f"{index}:{component_index}").strip(),
                            parent_sku=sku,
                            component_id=str(component.get("id") or component_sku).strip(),
                            origin_invoice_number=invoice_number,
                            origin_order_number=order_number,
                            note="Nachlieferung – nicht verrechnen",
                        )
                    )
                continue
            items.append(
                CustomerAftercareItemInput(
                    role="MISSING_TO_SEND",
                    sku=sku,
                    name=name or sku,
                    quantity=quantity,
                    sevdesk_part_id=str(part.get("id") or "").strip(),
                    source_unit_price=_decimal_or_none(position.get("price")),
                    source_tax_rate=_decimal_or_none(position.get("taxRate")),
                    source_discount_percent=_decimal_or_none(position.get("discount")),
                    source_kind="sevdesk_invoice_position",
                    source_item_id=str(position.get("id") or index).strip(),
                    origin_invoice_number=invoice_number,
                    origin_order_number=order_number,
                    note="Nachlieferung – nicht verrechnen",
                )
            )
        return items

    @staticmethod
    def _invoice_email(invoice: dict[str, Any]) -> str:
        contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
        return str(invoice.get("email") or contact.get("email") or "").strip()

    @staticmethod
    def _invoice_address_lines(invoice: dict[str, Any]) -> list[str]:
        contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
        shipping = invoice.get("shippingAddress") if isinstance(invoice.get("shippingAddress"), dict) else {}
        delivery = invoice.get("deliveryAddress") if isinstance(invoice.get("deliveryAddress"), dict) else {}
        address = shipping or delivery
        legacy_address = invoice.get("deliveryAddress") if isinstance(invoice.get("deliveryAddress"), str) else invoice.get("shippingAddress")
        values = [
            invoice.get("deliveryName") or invoice.get("shippingName") or address.get("name") or contact.get("name"),
            invoice.get("deliveryStreet") or invoice.get("shippingStreet") or address.get("street") or address.get("addressLine1"),
            invoice.get("deliveryAddressLine2") or invoice.get("shippingAddressLine2") or address.get("addressLine2") or legacy_address,
            " ".join(
                str(value).strip()
                for value in (
                    invoice.get("deliveryZip") or invoice.get("shippingZip") or address.get("zip") or address.get("postalCode"),
                    invoice.get("deliveryCity") or invoice.get("shippingCity") or address.get("city"),
                )
                if str(value or "").strip()
            ),
            invoice.get("deliveryCountry") or invoice.get("shippingCountry") or address.get("country") or invoice.get("addressCountry"),
        ]
        return [str(value).strip() for value in values if str(value or "").strip()]

    @staticmethod
    def _extract_order_number(invoice: dict[str, Any]) -> str:
        for key in ("orderNumber", "order_number", "externalReference", "reference", "description"):
            value = str(invoice.get(key) or "").strip()
            match = re.search(r"(?<!\d)(\d{5})(?!\d)", value)
            if match:
                return match.group(1)
        return ""


def _decimal_or_none(value: object):
    from decimal import Decimal, InvalidOperation

    try:
        if value is None or str(value).strip() == "":
            return None
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
