"""Idempotent sevDesk Zusatzrechnung for Lieferkorrektur cases (spec §8/§14).

Builds invoice positions directly from ``CustomerAftercareItem`` rows — NOT
via ``DraftInvoiceService``. That class only builds positions from a
resolved Wix order's own ``lineItems`` and has no manual-position or
percentage-discount support, which doesn't fit a Lieferkorrektur invoice
(e.g. "wrong item kept" or a courtesy-priced replacement-order-error
invoice, neither of which maps cleanly onto a fresh Wix order).

Idempotency (spec §14): every invoice this service creates carries the
marker ``LIEFERKORREKTUR:<case_uuid> | WIX:<source_order_number>`` in
``customerInternalNote``. Before EVERY create call — including a manual
"Zusatzrechnung erstellen" click, not only an automated retry —
``InvoiceClient.search_invoice_summaries`` is searched for the case UUID
and an existing match is reused instead of creating a duplicate.

Contact resolution is the caller's responsibility: this service takes an
already-resolved sevDesk ``contact_id`` and billing ``country_code`` as
explicit parameters. Wix-order-shaped contact matching already exists, in a
different shape, in ``DraftInvoiceService``/``ContactClient`` — a
Lieferkorrektur case may not have a fully resolved Wix order, so reusing
that logic here would need its own deliberate design rather than being
folded into this already tax/money-critical module.

Tax correctness is a hard stop, not a best-effort default: a missing
per-item tax rate or an unresolvable "custom" TaxSet raises rather than
silently guessing, since silently defaulting VAT treatment is a business
risk this feature must not introduce.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import uuid

from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.customer_aftercare.pricing_policy import (
    CustomerAftercarePricingPolicy,
    DiscountResult,
)
from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_office.services.sevdesk.tax_policy import CustomerAftercareTaxPolicy
from xw_office.services.sevdesk.tax_set_client import TaxSetClient

logger = logging.getLogger(__name__)

#: Item roles that get invoiced. MISSING_TO_SEND is what's still owed to the
#: customer free of charge — it is never billed.
_INVOICEABLE_ROLES = ("WRONG_DELIVERED", "CORRECTED_ORDER_ITEM", "SHIPPING")


def build_marker(case_id: uuid.UUID) -> str:
    return f"LIEFERKORREKTUR:{case_id}"


def build_marker_with_order(case_id: uuid.UUID, source_order_number: str) -> str:
    marker = build_marker(case_id)
    order = str(source_order_number or "").strip()
    return f"{marker} | WIX:{order}" if order else marker


@dataclass(frozen=True)
class InvoiceCreationResult:
    invoice_id: str
    invoice_number: str
    reused_existing: bool


def _extract_created_invoice(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        invoice = payload.get("invoice")
        if isinstance(invoice, dict):
            return invoice
        objects = payload.get("objects")
        if isinstance(objects, list) and objects and isinstance(objects[0], dict):
            return objects[0]
        if isinstance(objects, dict):
            return objects
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


class CustomerAftercareInvoiceService:
    """Create idempotent, correctly-priced/-taxed sevDesk Zusatzrechnungen (spec §8)."""

    def __init__(
        self,
        repo: CustomerAftercareRepository | None,
        invoice_client: InvoiceClient,
        tax_set_client: TaxSetClient,
        product_catalog: ProductCatalogService,
        pricing_policy: CustomerAftercarePricingPolicy,
        tax_policy: CustomerAftercareTaxPolicy,
    ) -> None:
        self._repo = repo
        self._invoices = invoice_client
        self._tax_sets = tax_set_client
        self._catalog = product_catalog
        self._pricing = pricing_policy
        self._tax = tax_policy

    def find_existing_invoice(self, case_id: uuid.UUID) -> InvoiceSummary | None:
        """Search sevDesk for an invoice already carrying this case's marker (spec §14)."""
        marker = build_marker(case_id)
        matches, _ = self._invoices.search_invoice_summaries(str(case_id))
        for summary in matches:
            if marker in (summary.sevdesk_reference or ""):
                return summary
        return None

    def create_invoice(
        self,
        case: CustomerAftercareCase,
        items: list[CustomerAftercareItem],
        *,
        contact_id: str,
        country_code: str,
    ) -> InvoiceCreationResult:
        """Create (or idempotently reuse) the Lieferkorrektur-Zusatzrechnung for *case*."""
        if self._repo is None:
            raise RuntimeError("Lieferkorrekturen-Datenbank ist nicht konfiguriert.")
        if not str(contact_id or "").strip():
            raise ValueError("sevDesk-Kontakt fehlt.")

        existing = self.find_existing_invoice(case.id)
        if existing is not None:
            logger.info(
                "Lieferkorrektur %s: bestehende Rechnung %s wiederverwendet (kein Duplikat erstellt)",
                case.id,
                existing.invoice_number,
            )
            self._repo.mark_invoice_created(
                case.id, sevdesk_invoice_id=existing.id, sevdesk_invoice_number=existing.invoice_number
            )
            return InvoiceCreationResult(existing.id, existing.invoice_number, reused_existing=True)

        invoiceable = [item for item in items if item.role in _INVOICEABLE_ROLES]
        if not invoiceable:
            raise RuntimeError("Kein verrechenbarer Artikel fuer diese Lieferkorrektur vorhanden.")
        missing_tax_rate = [item.name or item.sku for item in invoiceable if item.source_tax_rate is None]
        if missing_tax_rate:
            raise RuntimeError(
                "Steuersatz fehlt fuer: " + ", ".join(missing_tax_rate) + " — bitte vor Fakturierung ergaenzen."
            )

        is_b2b = case.customer_type == "B2B"
        tax_decision = self._tax.resolve(country_code=country_code, is_b2b=is_b2b)
        invoice: dict[str, object] = {
            "status": 100,
            "invoiceType": "RE",
            "taxType": tax_decision.tax_type,
            "customerInternalNote": build_marker_with_order(case.id, case.source_wix_order_number),
            "header": "Rechnung",
            "contact": {"id": contact_id, "objectName": "Contact"},
        }
        if tax_decision.tax_type == "custom":
            tax_set = self._tax_sets.find_by_text(tax_decision.tax_set_text)
            if tax_set is None:
                raise RuntimeError(
                    f"sevDesk-TaxSet '{tax_decision.tax_set_text}' ist im sevDesk-Konto nicht konfiguriert."
                )
            invoice["taxSet"] = {"id": tax_set.id, "objectName": "TaxSet"}
            invoice["taxText"] = tax_decision.tax_set_text

        product_discount = self._pricing.resolve_product_discount(courtesy=case.courtesy)
        shipping_discount = self._pricing.resolve_shipping_discount(courtesy=case.courtesy)
        positions = [
            self._build_position(
                item, index, shipping_discount if item.role == "SHIPPING" else product_discount
            )
            for index, item in enumerate(invoiceable, start=1)
        ]

        try:
            response = self._invoices.update_invoice_draft(invoice, positions)
        except Exception as exc:  # noqa: BLE001 - persist failure state before surfacing to the caller.
            self._repo.mark_invoice_failed(case.id, error_message=str(exc))
            raise

        created = _extract_created_invoice(response)
        created_id = str(created.get("id") or "").strip()
        created_number = str(created.get("invoiceNumber") or "").strip()
        if not created_id:
            self._repo.mark_invoice_failed(case.id, error_message="sevDesk hat keinen Rechnungsentwurf zurueckgegeben.")
            raise RuntimeError("sevDesk hat keinen Rechnungsentwurf zurueckgegeben.")

        self._repo.mark_invoice_created(
            case.id, sevdesk_invoice_id=created_id, sevdesk_invoice_number=created_number
        )
        logger.info("Lieferkorrektur %s: Rechnung %s erstellt", case.id, created_id)
        return InvoiceCreationResult(created_id, created_number or "(Entwurf)", reused_existing=False)

    def _build_position(
        self, item: CustomerAftercareItem, position_number: int, discount: DiscountResult
    ) -> dict[str, object]:
        part_ref = None
        sevdesk_part_id = str(item.sevdesk_part_id or "").strip()
        if not sevdesk_part_id and item.sku:
            product = self._catalog.resolve_sku(item.sku)
            if product is not None and product.sevdesk_part_id:
                sevdesk_part_id = product.sevdesk_part_id
        if sevdesk_part_id:
            part_ref = {"id": sevdesk_part_id, "objectName": "Part"}

        position: dict[str, object] = {
            "name": item.name or item.sku or "Position",
            "quantity": int(item.quantity or 1),
            "price": float(item.source_unit_price) if item.source_unit_price is not None else 0.0,
            "taxRate": float(item.source_tax_rate) if item.source_tax_rate is not None else 0.0,
            "positionNumber": position_number,
        }
        if part_ref is not None:
            position["part"] = part_ref
        if discount.percent:
            position["discount"] = discount.percent
            position["isPercentage"] = discount.is_percentage
        return position
