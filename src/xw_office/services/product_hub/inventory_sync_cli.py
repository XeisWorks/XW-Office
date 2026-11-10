"""One-shot sevDesk invoice/credit inventory feed for external releases."""
from __future__ import annotations

import argparse
import datetime as dt
import json

from xw_office.core.config import load_config
from xw_office.core.database import create_session_factory
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.http_client import build_sevdesk_connection
from xw_office.services.product_hub.invoice_inventory import (
    InvoiceInventoryBookingService,
    InvoiceInventoryLine,
)
from xw_office.services.product_hub.inventory_external_mirror import InventoryExternalMirrorService
from xw_office.services.product_hub.inventory import LegacyInventoryShadowBridge
from xw_office.services.product_hub.sevdesk_credit_note_inventory import SevdeskCreditNoteInventoryService
from xw_office.services.product_hub.sevdesk_history_audit import sevdesk_history_provider_from_connection
from xw_office.services.product_hub.sevdesk_invoice_inventory import SevdeskInvoiceInventoryPoller
from xw_office.services.product_hub.sevdesk_feed_checkpoint import (
    advance_invoice_feed_checkpoint,
    resolve_invoice_feed_since,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Book external finalized sevDesk inventory documents")
    parser.add_argument("--since", help="ISO date override for finalized invoice polling")
    parser.add_argument("--years", type=int, default=1, choices=range(1, 6), help="Credit-note history to rescan")
    args = parser.parse_args(argv)
    config = load_config()
    if not (config.database_url or "").strip():
        parser.error("DATABASE_URL is required")
    today = dt.date.today()
    requested_since = dt.date.fromisoformat(args.since) if args.since else None
    factory = create_session_factory(config)
    settings = SettingKvRepository(factory)
    since = resolve_invoice_feed_since(
        settings,
        requested_since=requested_since,
        today=today,
    )
    provider = sevdesk_history_provider_from_connection(build_sevdesk_connection(config))
    booking = InvoiceInventoryBookingService(factory)
    mirror = InventoryExternalMirrorService(factory)
    shadow_bridge = LegacyInventoryShadowBridge(factory)

    def mirror_line(line: InvoiceInventoryLine, booking_result: object) -> object:
        delta = int(getattr(booking_result, "delta", 0))
        target = int(getattr(booking_result, "requested_quantity_applied", 0))
        movement_kind = str(getattr(line, "movement_kind", "sale"))
        key = (
            f"external-feed:{movement_kind}:{line.document_id}:{line.position_key}:target:{target}"
        )
        result = mirror.apply(
            sku=booking.sku_for_variant(line.variant_id),
            delta=delta,
            idempotency_key=key,
            external_reference=f"{line.document_id}:{line.position_key}",
        )
        if result.status == "shortage":
            shadow_bridge.record_external_shortage(
                sku=result.sku,
                requested_delta=delta,
                current_on_hand=result.previous_stock,
                target_on_hand=result.new_stock,
                detail=result.detail,
                external_reference=f"{line.document_id}:{line.position_key}",
            )
        return result

    invoices = SevdeskInvoiceInventoryPoller(provider, booking, on_applied=mirror_line).poll(since=since)
    if not invoices.errors and not invoices.needs_review:
        advance_invoice_feed_checkpoint(settings, completed_through=today)
    credits = SevdeskCreditNoteInventoryService(provider, booking, on_applied=mirror_line)
    credit_processed = 0
    credit_already_applied = 0
    credit_needs_review: list[str] = []
    credit_errors: list[str] = []
    for year in range(today.year - int(args.years) + 1, today.year + 1):
        result = credits.process_year(year)
        credit_processed += result.processed
        credit_already_applied += result.already_applied
        credit_needs_review.extend(result.needs_review)
        credit_errors.extend(result.errors)
    credit_result = {
        "processed": credit_processed,
        "already_applied": credit_already_applied,
        "needs_review": credit_needs_review,
        "errors": credit_errors,
    }
    payload = {
        "invoice": invoices.__dict__,
        "credit_note": credit_result,
        "since": since.isoformat(),
        "invoice_checkpoint_advanced": not invoices.errors and not invoices.needs_review,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 1 if invoices.errors or invoices.needs_review or credit_errors or credit_needs_review else 0


if __name__ == "__main__":
    raise SystemExit(main())

