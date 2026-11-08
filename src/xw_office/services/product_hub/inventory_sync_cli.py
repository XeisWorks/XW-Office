"""One-shot sevDesk invoice/credit inventory feed for external releases."""
from __future__ import annotations

import argparse
import datetime as dt
import json

from xw_office.core.config import load_config
from xw_office.core.database import create_session_factory
from xw_office.services.http_client import build_sevdesk_connection
from xw_office.services.product_hub.invoice_inventory import InvoiceInventoryBookingService
from xw_office.services.product_hub.inventory_external_mirror import InventoryExternalMirrorService
from xw_office.services.product_hub.sevdesk_credit_note_inventory import SevdeskCreditNoteInventoryService
from xw_office.services.product_hub.sevdesk_history_audit import sevdesk_history_provider_from_connection
from xw_office.services.product_hub.sevdesk_invoice_inventory import SevdeskInvoiceInventoryPoller


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Book external finalized sevDesk inventory documents")
    parser.add_argument("--since", help="ISO date for finalized invoices (defaults to 7 days ago)")
    parser.add_argument("--years", type=int, default=1, choices=range(1, 6), help="Credit-note history to rescan")
    args = parser.parse_args(argv)
    config = load_config()
    if not (config.database_url or "").strip():
        parser.error("DATABASE_URL is required")
    today = dt.date.today()
    since = dt.date.fromisoformat(args.since) if args.since else today - dt.timedelta(days=7)
    factory = create_session_factory(config)
    provider = sevdesk_history_provider_from_connection(build_sevdesk_connection(config))
    booking = InvoiceInventoryBookingService(factory)
    mirror = InventoryExternalMirrorService(factory)

    def mirror_line(line, booking_result):
        delta = int(getattr(booking_result, "delta", 0))
        target = int(getattr(booking_result, "requested_quantity_applied", 0))
        movement_kind = str(getattr(line, "movement_kind", "sale"))
        key = (
            f"external-feed:{movement_kind}:{line.document_id}:{line.position_key}:target:{target}"
        )
        return mirror.apply(
            sku=booking.sku_for_variant(line.variant_id),
            delta=delta,
            idempotency_key=key,
            external_reference=f"{line.document_id}:{line.position_key}",
        )

    invoices = SevdeskInvoiceInventoryPoller(provider, booking, on_applied=mirror_line).poll(since=since)
    credits = SevdeskCreditNoteInventoryService(provider, booking, on_applied=mirror_line)
    credit_result = {"processed": 0, "already_applied": 0, "needs_review": [], "errors": []}
    for year in range(today.year - int(args.years) + 1, today.year + 1):
        result = credits.process_year(year)
        credit_result["processed"] += result.processed
        credit_result["already_applied"] += result.already_applied
        credit_result["needs_review"].extend(result.needs_review)
        credit_result["errors"].extend(result.errors)
    payload = {
        "invoice": invoices.__dict__,
        "credit_note": credit_result,
        "since": since.isoformat(),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 1 if invoices.errors or invoices.needs_review or credit_result["errors"] or credit_result["needs_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

