"""Create, preflight and repair sevDesk invoice drafts from Wix order numbers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import logging
from typing import Any

from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.invoice_client import InvoiceClient
from xw_studio.services.sevdesk.part_client import PartClient, SevdeskPart
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.services.wix.client import _parse_order_line_item

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductDraft:
    name: str
    sku: str
    text: str
    internal_comment: str
    price_gross: float | None
    tax_rate: float | None
    unity: dict[str, Any]
    category_id: str = ""
    category_name: str = ""


@dataclass(frozen=True)
class ProductIssueTarget:
    invoice_id: str
    invoice_number: str
    wix_order_number: str
    customer_name: str


@dataclass
class ProductIssue:
    sku: str
    wix_name: str
    wix_order_number: str
    wix_description: str
    wix_price_gross: float | None
    is_digital: bool
    draft: ProductDraft
    targets: list[ProductIssueTarget] = field(default_factory=list)


@dataclass(frozen=True)
class ProductIssueDecision:
    action: str
    draft: ProductDraft


@dataclass(frozen=True)
class ProductPreflightPlan:
    issues: list[ProductIssue]
    part_categories: list[dict[str, str]]


@dataclass(frozen=True)
class ProductPreflightApplyResult:
    created_skus: tuple[str, ...] = ()
    skipped_skus: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class DraftInvoiceService:
    """Build, preflight and repair sevDesk invoice drafts from Wix order data."""

    def __init__(
        self,
        connection: SevdeskConnection,
        wix_orders: WixOrdersClient,
        part_client: PartClient,
        contact_client: ContactClient,
        invoice_client: InvoiceClient,
    ) -> None:
        self._conn = connection
        self._wix_orders = wix_orders
        self._parts = part_client
        self._contacts = contact_client
        self._invoices = invoice_client

    def create_draft_from_wix_order_number(self, wix_order_number: str) -> dict[str, str]:
        """Create an Entwurf in sevDesk from a Wix order number."""
        reference = str(wix_order_number or "").strip()
        if not reference:
            raise ValueError("Wix-Order-Nr fehlt.")
        if not self._wix_orders.has_credentials():
            raise ValueError("Wix API nicht konfiguriert (API-Key/Account/Site-ID fehlt).")

        order = self._resolve_order_required(reference)
        order_number = str(order.get("number") or reference).strip()

        contact_id = self._resolve_or_create_contact(order)
        sev_user_id = self._resolve_default_sev_user_id()
        positions = self._build_positions(order)

        invoice_date = date.today().isoformat()
        invoice: dict[str, Any] = {
            "objectName": "Invoice",
            "mapAll": True,
            "invoiceDate": invoice_date,
            "deliveryDate": invoice_date,
            "status": 100,
            "invoiceType": "RE",
            "currency": "EUR",
            "contact": {"id": contact_id, "objectName": "Contact"},
            "discount": 0,
            "taxRate": 0,
            "taxType": "default",
            "customerInternalNote": order_number,
            "showNet": False,
            "header": "Rechnung",
            "address": self._build_address_text(order),
        }

        next_invoice_number = self._get_next_invoice_number()
        if next_invoice_number:
            invoice["invoiceNumber"] = next_invoice_number
        if sev_user_id:
            invoice["contactPerson"] = {"id": sev_user_id, "objectName": "SevUser"}

        payload = {
            "invoice": invoice,
            "invoicePosSave": positions,
            "invoicePosDelete": None,
            "discountSave": [],
            "discountDelete": None,
            "takeDefaultAddress": False,
        }
        response = self._conn.post("/Invoice/Factory/saveInvoice", json=payload)
        data = response.json() if response.content else {}
        created_invoice = self._extract_created_invoice(data)
        created_id = str(created_invoice.get("id") or "").strip()
        created_number = str(created_invoice.get("invoiceNumber") or "").strip()
        if not created_id:
            raise RuntimeError("sevDesk hat keinen Rechnungsentwurf zurueckgegeben.")

        logger.info("DraftInvoiceService: draft created for Wix order %s -> invoice %s", order_number, created_id)
        return {
            "invoice_id": created_id,
            "invoice_number": created_number or "(Entwurf)",
            "wix_order_number": order_number,
            "positions": str(len(positions)),
        }

    def preview_wix_order_number(self, wix_order_number: str) -> dict[str, Any]:
        """Return preview data for the draft popup before creation."""
        reference = str(wix_order_number or "").strip()
        if not reference:
            raise ValueError("Wix-Order-Nr fehlt.")
        if not self._wix_orders.has_credentials():
            raise ValueError("Wix API nicht konfiguriert (API-Key/Account/Site-ID fehlt).")

        order = self._resolve_order_required(reference)
        order_number = str(order.get("number") or reference).strip()
        items = self._wix_orders.fetch_order_line_items(order_number)
        if not items:
            raise ValueError("Wix-Order enthaelt keine Positionen.")

        missing_skus: list[str] = []
        create_dialog_skus: list[str] = []
        preview_items: list[dict[str, str]] = []
        for item in items:
            sku = str(item.sku or "").strip().upper()
            if not sku:
                missing_skus.append(f"(ohne SKU) {item.name}")
                preview_items.append(
                    {
                        "sku": "-",
                        "name": str(item.name or "").strip() or "(ohne Name)",
                        "qty": str(max(1, int(item.qty or 1))),
                        "status": "Nicht mappbar (SKU fehlt)",
                    }
                )
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not str(part.id).strip():
                create_dialog_skus.append(sku)
                preview_items.append(
                    {
                        "sku": sku,
                        "name": str(item.name or "").strip() or sku,
                        "qty": str(max(1, int(item.qty or 1))),
                        "status": "Produktdialog vor Erstellung",
                    }
                )
                continue
            preview_items.append(
                {
                    "sku": sku,
                    "name": str(item.name or part.name or sku).strip(),
                    "qty": str(max(1, int(item.qty or 1))),
                    "status": f"OK -> Part {part.id}",
                }
            )

        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        customer = " ".join(
            part
            for part in (str(buyer.get("firstName") or "").strip(), str(buyer.get("lastName") or "").strip())
            if part
        ).strip()
        return {
            "wix_order_number": order_number,
            "customer": customer or "-",
            "email": str(buyer.get("email") or "").strip() or "-",
            "items": preview_items,
            "missing_skus": sorted(set(missing_skus)),
            "auto_create_skus": sorted(set(create_dialog_skus)),
            "can_create": not bool(missing_skus),
        }

    def build_missing_product_plan(
        self,
        references: list[str],
        *,
        targets_by_reference: dict[str, list[ProductIssueTarget]] | None = None,
    ) -> ProductPreflightPlan:
        """Collect missing sevDesk parts for Wix orders, grouped by SKU."""
        normalized_refs = [str(ref or "").strip() for ref in references if str(ref or "").strip()]
        if not normalized_refs:
            return ProductPreflightPlan(issues=[], part_categories=self._parts.list_part_categories())

        issues_by_sku: dict[str, ProductIssue] = {}
        part_categories = self._parts.list_part_categories()
        existing_parts = self._parts_by_sku()

        for reference in normalized_refs:
            order = self._resolve_order_required(reference)
            order_number = str(order.get("number") or reference).strip()
            raw_items = self._order_line_items(order)
            if not raw_items:
                continue
            targets = list((targets_by_reference or {}).get(order_number) or [])
            if not targets:
                targets = [self._fallback_target_for_order(order_number, order)]
            for raw_item in raw_items:
                item = _parse_order_line_item(raw_item)
                sku = str(item.sku or "").strip().upper()
                if not sku:
                    continue
                if sku in existing_parts:
                    continue
                issue = issues_by_sku.get(sku)
                if issue is None:
                    draft = self._build_product_draft(
                        raw_item=raw_item,
                        categories=part_categories,
                        existing_parts=existing_parts,
                    )
                    issue = ProductIssue(
                        sku=sku,
                        wix_name=str(item.name or sku).strip(),
                        wix_order_number=order_number,
                        wix_description=str(item.note or "").strip(),
                        wix_price_gross=round(self._line_item_unit_price(raw_item), 2),
                        is_digital=self._wix_orders.line_item_is_digital(raw_item),
                        draft=draft,
                    )
                    issues_by_sku[sku] = issue
                self._merge_targets(issue.targets, targets)

        issues = sorted(issues_by_sku.values(), key=lambda issue: issue.sku)
        return ProductPreflightPlan(issues=issues, part_categories=part_categories)

    def apply_missing_product_plan(
        self,
        plan: ProductPreflightPlan,
        decisions: dict[str, ProductIssueDecision],
    ) -> ProductPreflightApplyResult:
        """Create chosen sevDesk products and patch affected drafts where possible."""
        created_skus: list[str] = []
        skipped_skus: list[str] = []
        warnings: list[str] = []

        for issue in plan.issues:
            decision = decisions.get(issue.sku)
            if decision is None or decision.action == "skip":
                skipped_skus.append(issue.sku)
                continue
            if decision.action != "create_part":
                warnings.append(f"SKU {issue.sku}: unbekannte Entscheidung {decision.action}")
                continue
            try:
                created = self._parts.find_part_by_sku(issue.sku)
                if created is None or not created.id.strip():
                    payload = self._draft_to_part_payload(decision.draft, issue)
                    created = self._parts.create_part(payload)
                if created.id.strip():
                    created_skus.append(issue.sku)
                    for target in issue.targets:
                        if not target.invoice_id.strip():
                            continue
                        try:
                            self.repair_draft_product_mapping(
                                target.invoice_id,
                                target.wix_order_number,
                                create_missing_products=False,
                            )
                        except Exception as exc:  # noqa: BLE001
                            warnings.append(
                                f"Rechnung {target.invoice_number or target.invoice_id}: Produktabgleich fehlgeschlagen ({exc})"
                            )
                else:
                    warnings.append(f"SKU {issue.sku}: sevDesk-Produkt wurde ohne ID erstellt")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"SKU {issue.sku}: Produkt konnte nicht angelegt werden ({exc})")

        if created_skus:
            logger.info(
                "DraftInvoiceService: created sevDesk parts from dialog for %s",
                ", ".join(sorted(set(created_skus))),
            )
        return ProductPreflightApplyResult(
            created_skus=tuple(sorted(set(created_skus))),
            skipped_skus=tuple(sorted(set(skipped_skus))),
            warnings=tuple(warnings),
        )

    def build_manual_wix_product_plan(
        self,
        *,
        sku: str,
        wix_name: str,
        wix_product_id: str = "",
        wix_description: str = "",
        wix_price_gross: float | None = None,
        is_digital: bool = False,
    ) -> ProductPreflightPlan:
        """Build a one-item product preflight plan for manual product creation from Produkte/Wix views."""
        normalized_sku = str(sku or "").strip().upper()
        if not normalized_sku:
            raise ValueError("SKU fehlt.")

        part_categories = self._parts.list_part_categories()
        existing_parts = self._parts_by_sku()
        category = self._infer_part_category(
            sku=normalized_sku,
            is_digital=is_digital,
            categories=part_categories,
            existing_parts=existing_parts,
        )
        issue = ProductIssue(
            sku=normalized_sku,
            wix_name=str(wix_name or normalized_sku).strip() or normalized_sku,
            wix_order_number="",
            wix_description=str(wix_description or "").strip(),
            wix_price_gross=wix_price_gross,
            is_digital=is_digital,
            draft=ProductDraft(
                name=str(wix_name or normalized_sku).strip() or normalized_sku,
                sku=normalized_sku,
                text=str(wix_description or "").strip(),
                internal_comment=str(wix_product_id or "").strip(),
                price_gross=round(float(wix_price_gross), 2) if wix_price_gross is not None else None,
                tax_rate=19.0,
                unity={"id": 1, "objectName": "Unity"},
                category_id=str(category.get("id") or "").strip(),
                category_name=str(category.get("name") or "").strip(),
            ),
        )
        return ProductPreflightPlan(issues=[issue], part_categories=part_categories)

    def create_part_from_decision(self, issue: ProductIssue, decision: ProductIssueDecision) -> SevdeskPart:
        """Create a sevDesk part from a dialog decision for one manual product issue."""
        if decision.action != "create_part":
            raise ValueError(f"Nur create_part wird unterstuetzt, nicht {decision.action!r}")
        existing = self._parts.find_part_by_sku(issue.sku)
        if existing is not None and existing.id.strip():
            return existing
        payload = self._draft_to_part_payload(decision.draft, issue)
        return self._parts.create_part(payload)

    def repair_draft_product_mapping(
        self,
        invoice_id: str,
        wix_order_number: str,
        *,
        create_missing_products: bool = False,
    ) -> bool:
        """Patch an existing draft so invoice positions point to real sevDesk parts."""
        order = self._resolve_order_required(wix_order_number)
        if create_missing_products:
            self.ensure_products_for_wix_order_number(wix_order_number)
        invoice = self._invoices.fetch_invoice_by_id(invoice_id)
        positions = self._invoices.fetch_invoice_positions(invoice_id)
        if not invoice or not positions:
            return False
        patched_positions = self._patched_positions_for_order(order, positions)
        if patched_positions == positions:
            return False
        self._invoices.update_invoice_draft(invoice, patched_positions)
        logger.info("DraftInvoiceService: repaired draft %s for Wix order %s", invoice_id, wix_order_number)
        return True

    def ensure_products_for_wix_order_number(self, wix_order_number: str) -> list[str]:
        """Create missing sevDesk parts for one Wix order before draft creation."""
        order = self._resolve_order_required(wix_order_number)
        created: list[str] = []
        for raw_item in self._order_line_items(order):
            item = _parse_order_line_item(raw_item)
            sku = str(item.sku or "").strip().upper()
            if not sku:
                continue
            if self._parts.find_part_by_sku(sku) is not None:
                continue
            payload = self._build_part_payload(raw_item)
            created_part = self._parts.create_part(payload)
            if created_part.id.strip():
                created.append(sku)
        if created:
            logger.info("DraftInvoiceService: auto-created sevDesk parts for %s", ", ".join(sorted(set(created))))
        return created

    def _build_positions(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = self._order_line_items(order)
        if not raw_items:
            raise ValueError("Wix-Order enthaelt keine Positionen.")

        missing_skus: list[str] = []
        positions: list[dict[str, Any]] = []
        for index, raw_item in enumerate(raw_items):
            item = _parse_order_line_item(raw_item)
            sku = str(item.sku or "").strip().upper()
            if not sku:
                missing_skus.append(f"(ohne SKU) {item.name}")
                continue
            part = self._parts.find_part_by_sku(sku)
            qty = max(1, int(item.qty or 1))
            price = self._to_float(part.price_eur) if part is not None else 0.0
            if price <= 0:
                price = self._line_item_unit_price(raw_item)
            position: dict[str, Any] = {
                "objectName": "InvoicePos",
                "mapAll": True,
                "unity": {"id": 1, "objectName": "Unity"},
                "taxRate": float(part.tax_rate) if part is not None and part.tax_rate is not None else 19.0,
                "quantity": float(qty),
                "price": price,
                "name": str(item.name or (part.name if part is not None else "") or sku).strip(),
                "text": str(item.note or (part.text if part is not None else "") or "").strip(),
                "positionNumber": index,
            }
            if part is not None and str(part.id).strip():
                position["part"] = {"id": str(part.id), "objectName": "Part"}
                unity = part.unity if isinstance(part.unity, dict) else {}
                if unity.get("id"):
                    position["unity"] = dict(unity)
            positions.append(position)

        if missing_skus:
            joined = ", ".join(sorted(set(missing_skus)))
            raise ValueError(
                "Rechnungsentwurf abgebrochen: folgende Wix-Produkte sind nicht eindeutig auf sevDesk-Artikel gemappt: "
                f"{joined}"
            )
        if not positions:
            raise ValueError("Rechnungsentwurf abgebrochen: keine gueltigen Positionen gefunden.")
        return positions

    def _patched_positions_for_order(
        self,
        order: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_items = self._order_line_items(order)
        if not raw_items or not positions:
            return list(positions or [])
        patched = [dict(position) for position in positions]
        limit = min(len(raw_items), len(patched))
        for index in range(limit):
            raw_item = raw_items[index]
            item = _parse_order_line_item(raw_item)
            sku = str(item.sku or "").strip().upper()
            if not sku:
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not part.id.strip():
                continue
            updated = dict(patched[index])
            updated["part"] = {"id": str(part.id), "objectName": "Part"}
            updated["name"] = str(item.name or part.name or sku).strip()
            updated["text"] = str(item.note or part.text or updated.get("text") or "").strip()
            if part.unity and isinstance(part.unity, dict) and part.unity.get("id"):
                updated["unity"] = dict(part.unity)
            if part.tax_rate is not None:
                updated["taxRate"] = float(part.tax_rate)
            patched[index] = updated
        return patched

    @staticmethod
    def _order_line_items(order: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = order.get("lineItems") if isinstance(order, dict) else None
        if not isinstance(raw_items, list):
            return []
        return [item for item in raw_items if isinstance(item, dict)]

    def _draft_to_part_payload(self, draft: ProductDraft, issue: ProductIssue) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": str(draft.name or "").strip() or issue.sku,
            "partNumber": str(draft.sku or issue.sku).strip().upper(),
            "text": str(draft.text or "").strip(),
            "internalComment": str(draft.internal_comment or "").strip(),
            "priceGross": round(float(draft.price_gross or issue.wix_price_gross or 0.0), 2),
            "taxRate": float(draft.tax_rate if draft.tax_rate is not None else 19.0),
            "unity": dict(draft.unity or {"id": 1, "objectName": "Unity"}),
            "stockEnabled": not issue.is_digital,
            "stock": 0,
            "status": 100,
        }
        if draft.category_id:
            payload["category"] = {"id": draft.category_id, "objectName": "Category"}
        return payload

    def _build_part_payload(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        item = _parse_order_line_item(raw_item)
        sku = str(item.sku or "").strip().upper()
        name = str(item.name or sku).strip() or sku
        unity = {"id": 1, "objectName": "Unity"}
        return {
            "name": name,
            "partNumber": sku,
            "text": str(item.note or "").strip(),
            "priceGross": round(self._line_item_unit_price(raw_item), 2),
            "taxRate": 19.0,
            "unity": unity,
            "stockEnabled": not self._wix_orders.line_item_is_digital(raw_item),
            "stock": 0,
            "status": 100,
        }

    def _build_product_draft(
        self,
        *,
        raw_item: dict[str, Any],
        categories: list[dict[str, str]],
        existing_parts: dict[str, SevdeskPart],
    ) -> ProductDraft:
        item = _parse_order_line_item(raw_item)
        sku = str(item.sku or "").strip().upper()
        category = self._infer_part_category(
            sku=sku,
            is_digital=self._wix_orders.line_item_is_digital(raw_item),
            categories=categories,
            existing_parts=existing_parts,
        )
        return ProductDraft(
            name=str(item.name or sku).strip() or sku,
            sku=sku,
            text=str(item.note or "").strip(),
            internal_comment=str(
                raw_item.get("productId")
                or raw_item.get("catalogItemId")
                or ((raw_item.get("catalogReference") or {}).get("catalogItemId") if isinstance(raw_item.get("catalogReference"), dict) else "")
                or ""
            ).strip(),
            price_gross=round(self._line_item_unit_price(raw_item), 2),
            tax_rate=19.0,
            unity={"id": 1, "objectName": "Unity"},
            category_id=str(category.get("id") or "").strip(),
            category_name=str(category.get("name") or "").strip(),
        )

    def _infer_part_category(
        self,
        *,
        sku: str,
        is_digital: bool,
        categories: list[dict[str, str]],
        existing_parts: dict[str, SevdeskPart],
    ) -> dict[str, str]:
        if not categories:
            return {"id": "", "name": ""}

        prefix = sku[:4].upper()
        by_id: dict[str, dict[str, str]] = {str(entry.get("id") or ""): dict(entry) for entry in categories}
        counts: dict[str, int] = {}
        for part in existing_parts.values():
            if not part.category_id or not part.sku.upper().startswith(prefix):
                continue
            counts[part.category_id] = counts.get(part.category_id, 0) + 1
        if counts:
            category_id = max(counts.items(), key=lambda item: item[1])[0]
            chosen = by_id.get(category_id)
            if chosen:
                return chosen

        for entry in categories:
            name = str(entry.get("name") or "").casefold()
            if is_digital and "digital" in name:
                return dict(entry)
            if (not is_digital) and "digital" not in name:
                return dict(entry)
        return dict(categories[0])

    def _parts_by_sku(self) -> dict[str, SevdeskPart]:
        mapping: dict[str, SevdeskPart] = {}
        for part in self._parts.list_parts(max_pages=40):
            sku = str(part.sku or "").strip().upper()
            if sku and sku not in mapping:
                mapping[sku] = part
        return mapping

    @staticmethod
    def _merge_targets(existing: list[ProductIssueTarget], new_targets: list[ProductIssueTarget]) -> None:
        seen = {(target.invoice_id, target.wix_order_number) for target in existing}
        for target in new_targets:
            key = (target.invoice_id, target.wix_order_number)
            if key in seen:
                continue
            seen.add(key)
            existing.append(target)

    @staticmethod
    def _fallback_target_for_order(order_number: str, order: dict[str, Any]) -> ProductIssueTarget:
        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        customer_name = " ".join(
            part
            for part in (str(buyer.get("firstName") or "").strip(), str(buyer.get("lastName") or "").strip())
            if part
        ).strip()
        return ProductIssueTarget(
            invoice_id="",
            invoice_number="(neu)",
            wix_order_number=order_number,
            customer_name=customer_name or "-",
        )

    def _resolve_order_required(self, reference: str) -> dict[str, Any]:
        order = self._wix_orders.resolve_order(str(reference or "").strip())
        if not order:
            raise ValueError(f"Wix-Order '{reference}' wurde nicht gefunden.")
        return order

    def _resolve_or_create_contact(self, order: dict[str, Any]) -> str:
        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        email = str(buyer.get("email") or "").strip().lower()
        if email:
            contacts = self._contacts.list_contacts(max_pages=20, depth=1)
            for contact in contacts:
                if str(contact.email or "").strip().lower() == email:
                    return str(contact.id)

        billing = order.get("billingInfo") if isinstance(order.get("billingInfo"), dict) else {}
        contact_details = billing.get("contactDetails") if isinstance(billing.get("contactDetails"), dict) else {}
        first = str(contact_details.get("firstName") or "").strip()
        last = str(contact_details.get("lastName") or "").strip()
        company = str(contact_details.get("company") or "").strip()
        name = company or " ".join(part for part in (first, last) if part).strip() or email or "Wix Kunde"
        payload: dict[str, Any] = {
            "name": name,
            "status": 1000,
            "category": {"id": "3", "objectName": "Category"},
            "description": "Automatisch erstellt aus Wix-Bestellung",
        }
        response = self._conn.post("/Contact", json=payload)
        data = response.json() if response.content else {}
        contact_obj = self._extract_first_object(data)
        contact_id = str(contact_obj.get("id") or "").strip()
        if not contact_id:
            raise RuntimeError("Kontakt konnte in sevDesk nicht erstellt werden.")
        return contact_id

    def _resolve_default_sev_user_id(self) -> str:
        try:
            response = self._conn.get("/SevUser", params={"limit": 1, "offset": 0})
        except Exception:
            return ""
        data = response.json() if response.content else {}
        first = self._extract_first_object(data)
        return str(first.get("id") or "").strip()

    def _get_next_invoice_number(self) -> str:
        try:
            response = self._conn.get("/Invoice/Factory/getNextInvoiceNumber", params={"invoiceType": "RE"})
        except Exception:
            return ""
        payload = response.json() if response.content else {}
        if isinstance(payload, dict):
            objects = payload.get("objects")
            if isinstance(objects, list) and objects:
                first = objects[0]
                if isinstance(first, dict):
                    return str(first.get("invoiceNumber") or first.get("value") or "").strip()
                return str(first).strip()
            if isinstance(objects, dict):
                return str(objects.get("invoiceNumber") or objects.get("value") or "").strip()
        return ""

    def _build_address_text(self, order: dict[str, Any]) -> str:
        return "\n".join(WixOrdersClient.best_address_lines_from_order(order))

    @staticmethod
    def _extract_first_object(payload: object) -> dict[str, Any]:
        if isinstance(payload, dict):
            objects = payload.get("objects")
            if isinstance(objects, list) and objects and isinstance(objects[0], dict):
                return objects[0]
            if isinstance(objects, dict):
                return objects
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        return {}

    @staticmethod
    def _extract_created_invoice(payload: object) -> dict[str, Any]:
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

    @staticmethod
    def _line_item_unit_price(raw_item: dict[str, Any]) -> float:
        for key in ("price", "lineItemPrice", "priceBeforeDiscountsAndTax", "priceBeforeDiscounts"):
            value = DraftInvoiceService._extract_amount(raw_item.get(key))
            if value is not None:
                return value
        total = DraftInvoiceService._extract_amount(raw_item.get("totalPriceBeforeTax"))
        try:
            qty = max(1, int(raw_item.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        if total is not None:
            return total / max(qty, 1)
        return 0.0

    @staticmethod
    def _extract_amount(value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.replace(",", ".").strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None
        if isinstance(value, dict):
            amount = value.get("amount")
            if amount is None:
                return None
            return DraftInvoiceService._extract_amount(amount)
        return None

    @staticmethod
    def _to_float(value: object) -> float:
        try:
            return float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return 0.0
