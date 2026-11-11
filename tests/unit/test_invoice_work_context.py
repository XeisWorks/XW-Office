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


def test_invoice_position_preserves_optional_price_tax_discount_and_accounting_fields() -> None:
    position, = normalize_invoice_positions(
        [
            {
                "id": "priced-position",
                "positionNumber": 1,
                "part": {"partNumber": "XW-1"},
                "quantity": "2",
                "unity": "Stück",
                "price": "12.00",
                "priceNet": "10.00",
                "priceGross": "12.00",
                "priceTax": "2.00",
                "taxRate": "20",
                "discount": "5",
                "sumDiscount": "1.20",
                "sumNetAccounting": "19.00",
                "sumTaxAccounting": "3.80",
                "sumGrossAccounting": "22.80",
            }
        ]
    )

    assert position.unit == "Stück"
    assert position.unit_value == Decimal("12.00")
    assert position.unit_price_net == Decimal("10.00")
    assert position.unit_price_gross == Decimal("12.00")
    assert position.unit_tax == Decimal("2.00")
    assert position.tax_rate == Decimal("20")
    assert position.discount == Decimal("5")
    assert position.sum_discount == Decimal("1.20")
    assert position.sum_net_accounting == Decimal("19.00")
    assert position.sum_tax_accounting == Decimal("3.80")
    assert position.sum_gross_accounting == Decimal("22.80")


def test_invalid_optional_invoice_amounts_remain_absent() -> None:
    position, = normalize_invoice_positions(
        [
            {
                "part": {"partNumber": "XW-1"},
                "priceNet": "not-an-amount",
                "priceTax": "NaN",
                "taxRate": None,
                "sumGrossAccounting": "Infinity",
            }
        ]
    )

    assert position.unit_price_net is None
    assert position.unit_tax is None
    assert position.tax_rate is None
    assert position.sum_gross_accounting is None
    assert position.unit_value is None


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


def test_manual_invoice_address_tolerates_missing_or_malformed_nested_fields() -> None:
    summary = InvoiceSummary(id="43", contact_name="Fallback Name")
    billing, shipping, source = address_lines_from_invoice(
        {
            "contact": None,
            "addressZip": None,
            "addressCity": "Town",
            "shippingAddress": [],
            "deliveryName": "Recipient",
            "deliveryAddress": {"postalCode": "12345", "city": "Port"},
        },
        summary,
    )

    assert billing == ("Fallback Name", "Town")
    assert shipping == ("Recipient", "12345 Port")
    assert source == "sevdesk_delivery"


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
