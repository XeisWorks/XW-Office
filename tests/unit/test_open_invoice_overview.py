from __future__ import annotations

import types

from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.ui.modules.rechnungen.open_invoice_overview import (
    overview_from_visible_summaries,
    resolve_open_invoice_overview,
)


def test_open_invoice_overview_uses_cache_for_immediate_counts() -> None:
    summaries = [
        InvoiceSummary.model_validate(
            {
                "id": "phys",
                "invoiceNumber": "RE-P",
                "status": 100,
                "order_reference": "20910",
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "digital",
                "invoiceNumber": "RE-D",
                "status": 100,
                "order_reference": "20911",
            }
        ),
    ]

    overview = overview_from_visible_summaries(
        summaries,
        digital_cache={"20910": False, "20911": True},
    )

    assert overview.total == 2
    assert overview.with_ref == 2
    assert overview.physical == 1
    assert overview.digital == 1
    assert overview.unknown == 0
    assert overview.complete is True


def test_open_invoice_overview_reads_persistent_wix_cache_for_notes_and_products() -> None:
    summaries = [
        InvoiceSummary.model_validate(
            {
                "id": "phys",
                "invoiceNumber": "RE-P",
                "status": 100,
                "order_reference": "20910",
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "digital",
                "invoiceNumber": "RE-D",
                "status": 100,
                "order_reference": "20911",
            }
        ),
    ]

    class _CachedWix:
        def get_cached_reference_digital_only(self, reference: str) -> bool | None:
            return {"20910": False, "20911": True}.get(reference)

        def get_cached_order_buyer_note(self, reference: str) -> str:
            return "Bitte PLC Versandlabel pruefen" if reference == "20910" else ""

        def get_cached_order_line_items(self, reference: str) -> list[object] | None:
            if reference != "20910":
                return None
            return [
                types.SimpleNamespace(
                    sku="XW-PHYS",
                    name="Physisches Produkt",
                    qty=2,
                    note="Produktbeschreibung",
                )
            ]

    overview = overview_from_visible_summaries(
        summaries,
        digital_cache={},
        wix_client=_CachedWix(),  # type: ignore[arg-type]
    )

    assert overview.physical == 1
    assert overview.digital == 1
    assert overview.unknown == 0
    assert overview.with_note == 1
    assert overview.plc == 1
    assert overview.cache_updates == {"20910": False, "20911": True}
    assert [(item.title, item.description, item.quantity) for item in overview.print_products] == [
        ("Physisches Produkt", "Produktbeschreibung", 2)
    ]


def test_open_invoice_overview_filters_print_products_by_sku() -> None:
    summaries = [
        InvoiceSummary.model_validate(
            {
                "id": "phys",
                "invoiceNumber": "RE-P",
                "status": 100,
                "order_reference": "20910",
            }
        ),
    ]

    class _CachedWix:
        def get_cached_reference_digital_only(self, reference: str) -> bool | None:
            return False if reference == "20910" else None

        def get_cached_order_line_items(self, reference: str) -> list[object] | None:
            if reference != "20910":
                return None
            return [
                types.SimpleNamespace(sku="XW-PRINT", name="Print Produkt", qty=2, note=""),
                types.SimpleNamespace(sku="XW-OTHER", name="Normales Produkt", qty=1, note=""),
            ]

        def get_cached_order_buyer_note(self, _reference: str) -> str:
            return ""

    overview = overview_from_visible_summaries(
        summaries,
        digital_cache={},
        wix_client=_CachedWix(),  # type: ignore[arg-type]
        sku_filter=lambda sku: sku == "XW-PRINT",
    )

    assert [(item.sku, item.title, item.quantity) for item in overview.print_products] == [
        ("XW-PRINT", "Print Produkt", 2)
    ]


def test_open_invoice_overview_resolves_wix_notes_and_skips_cached_digital_lookup() -> None:
    summaries = [
        InvoiceSummary.model_validate(
            {
                "id": "phys",
                "invoiceNumber": "RE-P",
                "status": 100,
                "order_reference": "20910",
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "digital",
                "invoiceNumber": "RE-D",
                "status": 100,
                "order_reference": "20911",
            }
        ),
    ]

    class _InvoiceService:
        def resolve_invoice_list_hints(self, reference: str) -> object:
            note = "Bitte PLC Versandlabel pruefen" if reference == "20910" else "Digitale Lieferung"
            return types.SimpleNamespace(buyer_note=note)

    class _WixClient:
        calls: list[str] = []

        def has_credentials(self) -> bool:
            return True

        def is_reference_digital_only(self, reference: str) -> bool:
            self.calls.append(reference)
            return reference == "20911"

        def fetch_order_line_items(self, reference: str) -> list[object]:
            if reference != "20910":
                return []
            return [
                types.SimpleNamespace(
                    sku="XW-PHYS",
                    name="Physisches Produkt",
                    qty=3,
                    note="Produktbeschreibung",
                )
            ]

    wix_client = _WixClient()

    overview = resolve_open_invoice_overview(
        summaries,
        seq=7,
        invoice_service=_InvoiceService(),  # type: ignore[arg-type]
        wix_client=wix_client,  # type: ignore[arg-type]
        digital_cache={"20910": False},
        sku_filter=lambda sku: sku == "XW-PHYS",
    )

    assert overview.seq == 7
    assert overview.physical == 1
    assert overview.digital == 1
    assert overview.with_note == 2
    assert overview.plc == 1
    assert overview.cache_updates == {"20910": False, "20911": True}
    assert [(item.title, item.description, item.quantity) for item in overview.print_products] == [
        ("Physisches Produkt", "Produktbeschreibung", 3)
    ]
    assert wix_client.calls == ["20911"]
