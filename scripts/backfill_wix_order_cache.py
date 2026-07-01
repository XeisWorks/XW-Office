"""Backfill the persistent Wix order cache from recent sevDesk invoices.

This is a one-off maintenance tool.  It loads the newest sevDesk invoices
independent of status, resolves their Wix order references, and lets
``WixOrdersClient`` persist both found and missing results in the local SQLite
cache.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xw_studio.bootstrap import register_default_services  # noqa: E402
from xw_studio.core.config import load_config  # noqa: E402
from xw_studio.core.container import Container  # noqa: E402
from xw_studio.services.invoice_processing.service import InvoiceProcessingService  # noqa: E402
from xw_studio.services.wix.client import WixOrdersClient  # noqa: E402
from xw_studio.services.wix.order_cache import WixOrderCache  # noqa: E402


logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill local Wix order cache from the newest sevDesk invoices."
    )
    parser.add_argument("--limit", type=int, default=50, help="Number of newest sevDesk invoices.")
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="sevDesk list offset; leave 0 for the newest invoices.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = load_config()
    container = Container(config)
    register_default_services(container)

    invoice_service: InvoiceProcessingService = container.resolve(InvoiceProcessingService)
    wix_client: WixOrdersClient = container.resolve(WixOrdersClient)
    cache: WixOrderCache = container.resolve(WixOrderCache)

    if not wix_client.has_credentials():
        logger.error("Wix credentials missing; WIX_API_KEY and WIX_SITE_ID are required.")
        return 2

    summaries = invoice_service.load_invoice_summaries(
        status=None,
        limit=max(1, int(args.limit)),
        offset=max(0, int(args.offset)),
    )
    refs: list[str] = []
    seen: set[str] = set()
    skipped_without_ref = 0
    for summary in summaries:
        ref = str(summary.order_reference or "").strip()
        if not ref:
            skipped_without_ref += 1
            continue
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)

    logger.info(
        "Backfill start invoices=%s refs=%s skipped_without_ref=%s cache=%s",
        len(summaries),
        len(refs),
        skipped_without_ref,
        cache.path,
    )

    found = 0
    missing = 0
    failed = 0
    for idx, ref in enumerate(refs, start=1):
        try:
            meta = wix_client.resolve_order_summary(ref)
            if meta:
                # The summary lookup already stores the raw Wix order snapshot.
                # This call verifies that line items can be read from that same
                # cached snapshot without changing the cache policy.
                wix_client.fetch_order_line_items(ref)
                found += 1
                logger.info("[%s/%s] cached ref=%s found", idx, len(refs), ref)
            else:
                missing += 1
                logger.info("[%s/%s] cached ref=%s missing", idx, len(refs), ref)
        except Exception as exc:  # noqa: BLE001 - one bad order must not abort the backfill.
            failed += 1
            logger.warning("[%s/%s] ref=%s failed: %s", idx, len(refs), ref, exc)

    logger.info(
        "Backfill done found=%s missing=%s failed=%s skipped_without_ref=%s cache=%s",
        found,
        missing,
        failed,
        skipped_without_ref,
        cache.path,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
