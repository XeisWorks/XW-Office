"""Tests for Wix order-number extraction from sevDesk references."""
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


def test_b2b_reference_uses_wix_order_number_after_customer_po() -> None:
    summary = InvoiceSummary.from_api_object(
        {
            "id": "79",
            "invoiceNumber": "R-79",
            "reference": "BE-129789 | 20804",
        }
    )

    assert summary.sevdesk_reference == "BE-129789 | 20804"
    assert summary.order_reference == "20804"
    assert summary.as_table_row()["WIX"] == "20804"
    assert "BE-129789" in summary.as_table_row()["ID"]


def test_b2c_reference_remains_five_digit_wix_order_number() -> None:
    summary = InvoiceSummary.from_api_object(
        {
            "id": "80",
            "invoiceNumber": "R-80",
            "reference": "20805",
        }
    )

    assert summary.order_reference == "20805"
    assert summary.as_table_row()["WIX"] == "20805"


def test_manual_invoice_without_reference_shows_dash_in_wix_column() -> None:
    summary = InvoiceSummary.from_api_object(
        {
            "id": "81",
            "invoiceNumber": "R-81",
            "reference": "",
        }
    )

    assert summary.order_reference == ""
    assert summary.as_table_row()["WIX"] == "\u2014"
    assert not summary.as_table_row()["__has_order_ref__"]
