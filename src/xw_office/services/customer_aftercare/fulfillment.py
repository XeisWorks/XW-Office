"""Lieferschein/Nachsendung integration for Lieferkorrektur cases (spec §11).

Pure helpers only — no I/O. These feed into the existing, already-tested
Offene-Sendungen pipeline (label/PDF rendering, print queue, manual-fields
editing) via ``OffeneSendungenService.create_manual_case`` rather than any
new fulfillment code path; this module never rewrites or bypasses it.
"""
from __future__ import annotations

from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.services.sendungen.service import SendungProductLine


def manual_case_id(case: CustomerAftercareCase) -> str:
    """Stable synthetic Offene-Sendungen case id for a Lieferkorrektur case."""
    return f"lieferkorrektur-{case.id}"


def replacement_shipment_note(case: CustomerAftercareCase) -> str:
    """Lieferschein note text for a Lieferkorrektur-originated Nachsendung (spec §11 examples)."""
    order = str(case.source_wix_order_number or "").strip()
    if case.case_type == "B2B_MISSING_ITEMS" and order:
        return f"Kostenlose Nachlieferung zu Bestellung {order} — Lieferkorrektur, nicht verrechnen."
    if order:
        return f"Nachsendung aufgrund Falschlieferung zu Bestellung {order} — Lieferkorrektur, nicht verrechnen."
    return "Nachsendung aufgrund Falschlieferung — Lieferkorrektur, nicht verrechnen."


def missing_items_as_product_lines(items: list[CustomerAftercareItem]) -> list[SendungProductLine]:
    """Convert a case's MISSING_TO_SEND items into free/no-return Sendung product lines.

    Always marked ``free_delivery=True``/``no_return_required=True`` — a
    Lieferkorrektur replacement is, by definition, something XeisWorks
    already owes the customer for free (spec §11).
    """
    return [
        SendungProductLine(
            quantity=str(item.quantity or 1),
            name=item.name or item.sku,
            sku=item.sku,
            note="Lieferkorrektur",
            free_delivery=True,
            no_return_required=True,
        )
        for item in items
        if item.role == "MISSING_TO_SEND"
    ]
