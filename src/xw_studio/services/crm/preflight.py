"""CRM merge preflight — read-only safety check before reassigning invoices.

Legacy ``crm_engine.merge_contacts`` blocked specific invoices from being
moved to the merge winner (finalized/"enshrined" invoices, invoices where
``invoiceDate < deliveryDate``) instead of aborting the whole merge, and
logged the reason per invoice. This module ports that classification as a
pure, testable function, used by :class:`~xw_studio.services.crm.service.CrmService`
as a dry-run step before any write happens — the same dry-run-before-live
pattern already established in ``xw_studio.services.xw_copilot``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


def _parse_date(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class MergeInvoiceDecision:
    """Whether one invoice of the merge loser can be safely reassigned."""

    invoice: "InvoiceSummary"
    movable: bool
    reason: str


def classify_invoice_for_merge(invoice: "InvoiceSummary") -> MergeInvoiceDecision:
    """Classify one invoice as movable or blocked for a CRM contact merge.

    Blocking rules (ported from legacy, see module docstring):
      * "enshrined": any invoice that already has a real invoice number
        (i.e. is no longer a draft) is considered finalized/immutable by
        sevDesk and must not be silently reassigned.
      * ``invoiceDate < deliveryDate``: a sevDesk validation constraint —
        an invoice already in this (invalid) state must not be touched
        automatically, since re-saving it could trip that validation.
    """
    if invoice.status_code != 100:
        return MergeInvoiceDecision(
            invoice,
            False,
            "Rechnung ist finalisiert (kein Entwurf mehr) und kann nicht automatisch "
            "umgehaengt werden.",
        )
    invoice_date = _parse_date(invoice.invoice_date)
    delivery_date = _parse_date(getattr(invoice, "delivery_date", None))
    if invoice_date is not None and delivery_date is not None and invoice_date < delivery_date:
        return MergeInvoiceDecision(
            invoice,
            False,
            "Rechnungsdatum liegt vor dem Lieferdatum (sevDesk-Validierungsregel) — "
            "manuell pruefen.",
        )
    return MergeInvoiceDecision(invoice, True, "Entwurf ohne Datumsproblem — sicher verschiebbar.")


@dataclass(frozen=True)
class MergePreflightReport:
    """Read-only result of scanning the merge loser's invoices."""

    duplicate_contact_id: str
    movable_invoices: tuple["InvoiceSummary", ...]
    blocked_invoices: tuple[MergeInvoiceDecision, ...]

    @property
    def has_blocked_invoices(self) -> bool:
        return bool(self.blocked_invoices)

    @property
    def invoice_count(self) -> int:
        return len(self.movable_invoices) + len(self.blocked_invoices)

    @property
    def has_no_invoices(self) -> bool:
        """True when the loser has no invoices at all — safe to delete outright."""
        return self.invoice_count == 0


def build_preflight_report(
    duplicate_contact_id: str,
    invoices: list["InvoiceSummary"],
) -> MergePreflightReport:
    movable: list["InvoiceSummary"] = []
    blocked: list[MergeInvoiceDecision] = []
    for invoice in invoices:
        decision = classify_invoice_for_merge(invoice)
        if decision.movable:
            movable.append(invoice)
        else:
            blocked.append(decision)
    return MergePreflightReport(duplicate_contact_id, tuple(movable), tuple(blocked))
