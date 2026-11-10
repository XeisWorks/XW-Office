from decimal import Decimal

import pytest

from xw_office.services.invoice_processing.context import (
    address_lines_from_invoice,
    build_capabilities,
    normalize_invoice_positions,
)
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


@pytest.mark.parametrize("value", [0, 0.0, "0", Decimal("0")])
def test_zero_quantity_does_not_become_one_printable_copy(value: object) -> None:
    position, = normalize_invoice_positions(
        [{"part": {"partNumber": "XW-1"}, "quantity": value, "qty": 9}]
    )
    assert position.quantity == Decimal("0")
    assert position.printable is False


@pytest.mark.parametrize("value", [None, ""])
def test_missing_quantity_uses_alternative_qty(value: object) -> None:
    position, = normalize_invoice_positions(
        [{"part": {"partNumber": "XW-1"}, "quantity": value, "qty": 2}]
    )
    assert position.quantity == Decimal("2")


def test_manual_invoice_positions_classify_products_shipping_and_services() -> None:
    positions = normalize_invoice_positions(
        [
            {
                "id": "p1",
                "positionNumber": 2,
                "part": {"id": "42", "partNumber": "XW-501.03", "name": "Hit"},
                "quantity": "2",
                "priceGross": "19.90",
            },
            {"id": "ship", "positionNumber": 3, "name": "Versandkosten", "quantity": 1},
            {"id": "note", "positionNumber": 4, "text": "Sonderleistung", "quantity": 1},
            {"id": "discount", "positionNumber": 5, "text": "Rabatt", "quantity": -1},
        ]
    )

    assert [position.kind for position in positions] == [
        "product",
        "shipping",
        "service",
        "discount",
    ]
    assert positions[0].sku == "XW-501.03"
    assert positions[0].quantity == Decimal("2")
    assert positions[0].printable is True
    assert positions[1].printable is False


def test_manual_invoice_address_falls_back_from_billing_to_shipping() -> None:
    summary = InvoiceSummary(id="42", contact_name="Roland Grunow")
    billing, shipping, source = address_lines_from_invoice(
        {
            "addressStreet": "Mühlenstraße 2",
            "addressZip": "17349",
            "addressCity": "Schönbeck",
            "addressCountryCode": "DE",
            "contact": {"name": "Roland Grunow", "email": "roland@example.test"},
        },
        summary,
    )

    assert billing == ("Roland Grunow", "Mühlenstraße 2", "17349 Schönbeck", "GERMANY")
    assert shipping == billing
    assert source == "billing_fallback"


def test_capabilities_disable_wix_but_enable_sevdesk_actions() -> None:
    positions = normalize_invoice_positions(
        [{"id": "p1", "part": {"partNumber": "XW-1"}, "name": "Notenheft", "quantity": 1}]
    )
    capabilities = build_capabilities(
        customer_email="customer@example.test",
        shipping_lines=("Name", "Straße 1", "10000 Stadt", "GERMANY"),
        positions=positions,
        has_wix_order=False,
    )

    assert capabilities.has_wix_order is False
    assert capabilities.can_print_address_label is True
    assert capabilities.can_create_plc_label is True
    assert capabilities.can_send_invoice is True
    assert capabilities.has_printable_products is True
