"""Open-invoice overview calculation for the Rechnungen view."""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrintProductAggregate:
    """One cross-invoice product line shown below the open-invoice summary."""

    sku: str
    title: str
    description: str
    quantity: int


@dataclass(frozen=True)
class OpenInvoiceOverview:
    """Counts shown in the OFFENE RECHNUNGEN box."""

    key: str
    total: int
    with_ref: int
    physical: int
    digital: int
    unknown: int
    with_note: int
    plc: int
    complete: bool
    cache_updates: dict[str, bool] = field(default_factory=dict)
    print_products: list[PrintProductAggregate] = field(default_factory=list)
    seq: int = 0

    @property
    def suffix(self) -> str:
        return "+" if self.unknown else ""


def open_invoice_overview_key(summaries: list[InvoiceSummary]) -> str:
    """Stable cache key that changes when the visible open-invoice set changes."""
    return "|".join(
        sorted(
            f"{str(summary.id or '').strip()}:"
            f"{summary.order_reference.strip()}:"
            f"{summary.buyer_note.strip()}"
            for summary in summaries
        )
    )


def overview_from_visible_summaries(
    summaries: list[InvoiceSummary],
    *,
    digital_cache: dict[str, bool],
    wix_client: WixOrdersClient | None = None,
    sku_filter: Callable[[str], bool] | None = None,
) -> OpenInvoiceOverview:
    """Build the immediate UI result from already-loaded sevDesk rows and cache."""
    total = len(summaries)
    with_ref = 0
    physical = 0
    digital = 0
    with_note = 0
    plc = 0
    known_refs: set[str] = set()
    cache_updates: dict[str, bool] = {}
    products = _ProductAccumulator(sku_filter=sku_filter)
    for summary in summaries:
        ref = str(summary.order_reference or "").strip()
        buyer_note = str(summary.buyer_note or "").strip()
        has_note = bool(buyer_note)
        has_plc = summary.has_plc_label_candidate()
        if ref:
            with_ref += 1
            cached_digital = digital_cache.get(ref) if ref in digital_cache else None
            if cached_digital is None and wix_client is not None:
                cached_digital = _cached_reference_digital_only(wix_client, ref)
                if cached_digital is not None:
                    cache_updates[ref] = cached_digital
            if cached_digital is not None and ref not in known_refs:
                known_refs.add(ref)
                if cached_digital:
                    digital += 1
                else:
                    physical += 1
                    cached_items = _cached_order_line_items(wix_client, ref) if wix_client is not None else None
                    if cached_items is not None:
                        products.add_items(cached_items)
            cached_note = _cached_order_buyer_note(wix_client, ref) if wix_client is not None else ""
            if cached_note:
                has_note = True
                has_plc = has_plc or note_has_plc_label_hint(cached_note)
        if has_note:
            with_note += 1
        if has_plc:
            plc += 1
    unknown = max(0, with_ref - len(known_refs))
    return OpenInvoiceOverview(
        key=open_invoice_overview_key(summaries),
        total=total,
        with_ref=with_ref,
        physical=physical,
        digital=digital,
        unknown=unknown,
        with_note=with_note,
        plc=plc,
        complete=unknown == 0,
        cache_updates=cache_updates,
        print_products=products.to_list(),
    )


def resolve_open_invoice_overview(
    summaries: list[InvoiceSummary],
    *,
    seq: int,
    invoice_service: InvoiceProcessingService,
    wix_client: WixOrdersClient,
    digital_cache: dict[str, bool] | None = None,
) -> OpenInvoiceOverview:
    """Resolve Wix-backed overview values without blocking the UI thread."""
    known_digital = dict(digital_cache or {})
    has_wix_credentials = wix_client.has_credentials()
    physical = 0
    digital = 0
    unknown = 0
    with_ref = 0
    with_note = 0
    plc = 0
    products = _ProductAccumulator(sku_filter=invoice_service.is_flagged_sku)
    workers = min(8, max(1, len(summaries)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="open-invoice-overview") as executor:
        rows = list(
            executor.map(
                lambda summary: _resolve_one_summary(
                    summary,
                    invoice_service=invoice_service,
                    wix_client=wix_client,
                    known_digital=known_digital,
                    has_wix_credentials=has_wix_credentials,
                ),
                summaries,
            )
        )

    cache_updates: dict[str, bool] = {}
    for row in rows:
        if row["has_ref"]:
            with_ref += 1
        if row["unknown"]:
            unknown += 1
        elif row["has_ref"]:
            is_digital = bool(row["digital"])
            ref = str(row["ref"])
            cache_updates[ref] = is_digital
            if is_digital:
                digital += 1
            else:
                physical += 1
                products.add_items(row["items"])
        if row["buyer_note"]:
            with_note += 1
        if row["has_plc"]:
            plc += 1

    return OpenInvoiceOverview(
        key=open_invoice_overview_key(summaries),
        total=len(summaries),
        with_ref=with_ref,
        physical=physical,
        digital=digital,
        unknown=unknown,
        with_note=with_note,
        plc=plc,
        complete=unknown == 0,
        cache_updates=cache_updates,
        print_products=products.to_list(),
        seq=seq,
    )


def _resolve_one_summary(
    summary: InvoiceSummary,
    *,
    invoice_service: InvoiceProcessingService,
    wix_client: WixOrdersClient,
    known_digital: dict[str, bool],
    has_wix_credentials: bool,
) -> dict[str, object]:
    ref = str(summary.order_reference or "").strip()
    buyer_note = str(summary.buyer_note or "").strip()
    has_plc = summary.has_plc_label_candidate()
    items: list[Any] = []
    if not ref:
        return {
            "ref": "",
            "has_ref": False,
            "digital": False,
            "unknown": False,
            "buyer_note": buyer_note,
            "has_plc": has_plc,
            "items": items,
        }
    buyer_note, has_plc = _resolve_hint_context(
        invoice_service,
        ref,
        buyer_note=buyer_note,
        has_plc=has_plc,
    )
    is_digital: bool | None = known_digital.get(ref)
    if is_digital is None:
        is_digital = _cached_reference_digital_only(wix_client, ref)
    if is_digital is None and has_wix_credentials:
        try:
            is_digital = bool(wix_client.is_reference_digital_only(ref))
        except Exception as exc:  # noqa: BLE001 - overview must stay partial.
            logger.debug("Open overview digital lookup failed ref=%s: %s", ref, exc)
    if is_digital is False:
        items = _order_line_items(wix_client, ref, has_wix_credentials=has_wix_credentials)
    return {
        "ref": ref,
        "has_ref": True,
        "digital": bool(is_digital),
        "unknown": is_digital is None,
        "buyer_note": buyer_note,
        "has_plc": has_plc,
        "items": items,
    }


def _resolve_hint_context(
    invoice_service: InvoiceProcessingService,
    reference: str,
    *,
    buyer_note: str,
    has_plc: bool,
) -> tuple[str, bool]:
    try:
        hints = invoice_service.resolve_invoice_list_hints(reference)
    except Exception as exc:  # noqa: BLE001 - overview must not break the list.
        logger.debug("Open overview hint lookup failed ref=%s: %s", reference, exc)
        return buyer_note, has_plc
    hint_note = str(getattr(hints, "buyer_note", "") or "").strip()
    return buyer_note or hint_note, has_plc or note_has_plc_label_hint(hint_note)


def note_has_plc_label_hint(note: object) -> bool:
    hay = str(note or "").strip().lower()
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
    )


class _ProductAccumulator:
    def __init__(self, *, sku_filter: Callable[[str], bool] | None = None) -> None:
        self._rows: dict[tuple[str, str, str], int] = defaultdict(int)
        self._sku_filter = sku_filter

    def add_items(self, items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            sku = str(getattr(item, "sku", "") or "").strip().upper()
            if self._sku_filter is not None and not self._sku_filter(sku):
                continue
            title = str(getattr(item, "name", "") or "").strip() or sku or "Unbenanntes Produkt"
            description = str(getattr(item, "note", "") or "").strip()
            try:
                qty = max(1, int(getattr(item, "qty", 1) or 1))
            except (TypeError, ValueError):
                qty = 1
            self._rows[(sku, title, description)] += qty

    def to_list(self) -> list[PrintProductAggregate]:
        rows = [
            PrintProductAggregate(
                sku=sku,
                title=title,
                description=description,
                quantity=quantity,
            )
            for (sku, title, description), quantity in self._rows.items()
        ]
        return sorted(rows, key=lambda row: (row.title.casefold(), row.description.casefold(), row.sku))


def _cached_reference_digital_only(wix_client: WixOrdersClient, reference: str) -> bool | None:
    resolver = getattr(wix_client, "get_cached_reference_digital_only", None)
    if not callable(resolver):
        return None
    try:
        value = resolver(reference)
    except Exception as exc:  # noqa: BLE001 - cache must never break overview.
        logger.debug("Cached digital lookup failed ref=%s: %s", reference, exc)
        return None
    return value if isinstance(value, bool) else None


def _cached_order_buyer_note(wix_client: WixOrdersClient | None, reference: str) -> str:
    resolver = getattr(wix_client, "get_cached_order_buyer_note", None)
    if not callable(resolver):
        return ""
    try:
        return str(resolver(reference) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Cached buyer-note lookup failed ref=%s: %s", reference, exc)
        return ""


def _cached_order_line_items(wix_client: WixOrdersClient | None, reference: str) -> list[Any] | None:
    resolver = getattr(wix_client, "get_cached_order_line_items", None)
    if not callable(resolver):
        return None
    try:
        items = resolver(reference)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Cached line-item lookup failed ref=%s: %s", reference, exc)
        return None
    return items if isinstance(items, list) else None


def _order_line_items(
    wix_client: WixOrdersClient,
    reference: str,
    *,
    has_wix_credentials: bool,
) -> list[Any]:
    cached = _cached_order_line_items(wix_client, reference)
    if cached is not None:
        return cached
    if not has_wix_credentials:
        return []
    try:
        items = wix_client.fetch_order_line_items(reference)
    except Exception as exc:  # noqa: BLE001 - product list is supplementary.
        logger.debug("Open overview line-item lookup failed ref=%s: %s", reference, exc)
        return []
    return items if isinstance(items, list) else []


def overview_payload_from_object(payload: object) -> OpenInvoiceOverview | None:
    if isinstance(payload, OpenInvoiceOverview):
        return payload
    if not isinstance(payload, dict):
        return None
    cache_updates_raw = payload.get("cache_updates")
    cache_updates: dict[str, bool] = {}
    if isinstance(cache_updates_raw, dict):
        cache_updates = {str(key): bool(value) for key, value in cache_updates_raw.items()}
    return OpenInvoiceOverview(
        key=str(payload.get("overview_key") or payload.get("key") or ""),
        total=_int_value(payload.get("total")),
        with_ref=_int_value(payload.get("with_ref")),
        physical=_int_value(payload.get("physical")),
        digital=_int_value(payload.get("digital")),
        unknown=_int_value(payload.get("unknown")),
        with_note=_int_value(payload.get("with_note")),
        plc=_int_value(payload.get("plc")),
        complete=not bool(payload.get("unknown")),
        cache_updates=cache_updates,
        print_products=[],
        seq=_int_value(payload.get("seq")),
    )


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
