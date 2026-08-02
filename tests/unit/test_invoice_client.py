"""Tests for sevDesk invoice DTO parsing."""
import base64
from datetime import date, datetime, timedelta, timezone
import json
import httpx

from xw_office.core.config import AppConfig
from xw_office.services.http_client import SevdeskConnection
from xw_office.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary


def test_invoice_summary_from_api_object() -> None:
    raw = {
        "id": 12,
        "invoiceNumber": "R-99",
        "invoiceDate": "2024-03-01",
        "status": "200",
        "sumGross": 19.99,
        "contact": {"name": "Test GmbH"},
    }
    summary = InvoiceSummary.from_api_object(raw)
    assert summary.id == "12"
    assert summary.invoice_number == "R-99"
    assert summary.status_code == 200
    assert summary.contact_name == "Test GmbH"
    row = summary.as_table_row()
    assert row["sevDesk"] == "R-99"
    assert row["WIX"] == "—"
    assert row["🔎"] == "🟠"
    assert row["Datum"] == "01.03.24"
    assert row["BETRAG"] == "19,99 €"
    assert "Test GmbH" in summary.detail_lines()
    assert summary.formatted_date == "01.03.2024"
    assert "19,99 €" in summary.formatted_brutto


def test_invoice_summary_flags_delivery_override_and_sensitive_country() -> None:
    raw = {
        "id": 99,
        "invoiceNumber": "R-100",
        "invoiceDate": "2024-04-01",
        "status": 200,
        "sumGross": 49.0,
        "contact": {"name": "Risk Co"},
        "addressCountry": {"code": "RU"},
        "street": "Alpha 1",
        "zip": "1010",
        "city": "Wien",
        "deliveryStreet": "Beta 9",
        "deliveryZip": "9999",
        "deliveryCity": "Berlin",
        "buyerNote": "Bitte ohne Klingeln",
    }

    summary = InvoiceSummary.from_api_object(raw)
    assert summary.has_delivery_address_override is True
    assert summary.is_sensitive_country is True
    row = summary.as_table_row()
    assert row["Hinweise"] == "✎ ⌂ ⚠"
    assert row["__icons__Hinweise"] == ["note", "alternateshippingaddress", "country"]
    assert "Käufernotiz" in row["__tooltip__Hinweise"]
    assert "Heikles Zielland" in row["__tooltip__Hinweise"]
    details = summary.detail_lines()
    assert "Lieferanschrift: abweichend" in details
    assert "Achtung: heikles Land" in details


def test_invoice_summary_highlights_draft_status() -> None:
    summary = InvoiceSummary.model_validate(
        {
            "id": "17",
            "invoiceNumber": "R-17",
            "status": 100,
        }
    )

    row = summary.as_table_row()

    assert row["🔎"] == "📝"
    assert row["__icons__Hinweise"] == []
    assert "abgearbeitet" in row["__tooltip__🔎"]


def test_invoice_summary_detects_plc_and_adds_plc_icon() -> None:
    summary = InvoiceSummary.model_validate(
        {
            "id": "31",
            "invoiceNumber": "R-31",
            "status": 200,
            "buyer_note": "Bitte mit PLC Label versenden",
        }
    )

    assert summary.has_plc_label_candidate() is True
    row = summary.as_table_row()
    assert row["__plc__enabled"] is True
    assert "plc" not in row["__icons__Hinweise"]


def test_invoice_client_list_parses_objects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/Invoice" in str(request.url)
        body = {
            "objects": [
                {
                    "id": 1,
                    "invoiceNumber": "A",
                    "invoiceDate": "2024-01-01",
                    "status": 1000,
                    "sumGross": "10",
                    "contact": {"name": "ACME"},
                }
            ]
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    cfg = AppConfig()
    conn = SevdeskConnection(client=client, config=cfg)
    inv = InvoiceClient(conn)
    rows = inv.list_invoice_summaries(embed_contact=False)
    assert len(rows) == 1
    assert rows[0].invoice_number == "A"
    assert rows[0].status_label() == "Bezahlt"


def test_invoice_client_fetch_invoice_positions_uses_invoice_filter_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/InvoicePos")
        params = dict(request.url.params)
        assert params["invoice[id]"] == "123"
        assert params["invoice[objectName]"] == "Invoice"
        assert params["embed"] == "part"
        return httpx.Response(200, json={"objects": [{"id": "POS-1", "name": "Artikel"}]})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    cfg = AppConfig()
    conn = SevdeskConnection(client=client, config=cfg)
    inv = InvoiceClient(conn)

    positions = inv.fetch_invoice_positions("123")

    assert len(positions) == 1
    assert positions[0]["id"] == "POS-1"


def test_invoice_client_extracts_q1_2026_objects_pdf_payload() -> None:
    pdf = b"%PDF-1.7\nq1-2026"
    payload = {"objects": {"pdf": base64.b64encode(pdf).decode("ascii")}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    inv = InvoiceClient(SevdeskConnection(client=client, config=AppConfig()))

    assert inv.extract_pdf_from_payload(payload) == pdf


def test_invoice_client_render_requests_pdf_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Invoice/123/render")
        assert request.url.params["getAsPdf"] == "true"
        return httpx.Response(200, json={"objects": {"pdf": ""}})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    inv = InvoiceClient(SevdeskConnection(client=client, config=AppConfig()))

    assert inv.render_invoice_pdf("123") == {"objects": {"pdf": ""}}


def test_invoice_client_confirms_paid_invoice_even_if_status_400_patch_does_not_stick() -> None:
    invoice_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal invoice_reads
        path = request.url.path
        if request.method == "GET" and path.endswith("/Invoice/123"):
            invoice_reads += 1
            status = 200 if invoice_reads == 1 else 1000
            return httpx.Response(200, json={"objects": {"id": 123, "status": status}})
        if request.method == "GET" and path.endswith("/CheckAccountTransaction/99"):
            return httpx.Response(
                200,
                json={"objects": {"id": 99, "status": 100, "checkAccount": {"id": 11}}},
            )
        if request.method == "GET" and path.endswith("/Tools/bookkeepingSystemVersion"):
            return httpx.Response(200, json={"objects": {"version": "2.0"}})
        if request.method == "PUT" and path.endswith("/Invoice/123/bookAmount"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["checkAccountTransaction"] == {"id": 99, "objectName": "CheckAccountTransaction"}
            return httpx.Response(200, json={"objects": {}})
        if request.method == "PUT" and path.endswith("/CheckAccountTransaction/99"):
            return httpx.Response(200, json={"objects": {"id": 99, "status": 100}})
        return httpx.Response(404, text=f"unexpected {request.method} {path}")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    inv = InvoiceClient(SevdeskConnection(client=client, config=AppConfig()))

    result = inv.book_invoice_with_transaction(
        123,
        29.9,
        check_account_id=11,
        transaction_id=99,
        booking_date=int(datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc).timestamp()),
    )

    assert result["status"] == "booked"
    assert result["tx_status"] == "100"


def test_invoice_client_search_matches_wix_order_and_customer_within_initial_window() -> None:
    today = date.today()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Invoice")
        body = {
            "objects": [
                {
                    "id": 3,
                    "invoiceNumber": "RE-300",
                    "invoiceDate": today.isoformat(),
                    "status": 200,
                    "sumGross": "48.80",
                    "customerInternalNote": "20522",
                    "contact": {
                        "name": "XeisWorks",
                        "surename": "Felix",
                        "familyname": "Griesbach",
                    },
                },
                {
                    "id": 2,
                    "invoiceNumber": "RE-200",
                    "invoiceDate": (today - timedelta(days=10)).isoformat(),
                    "status": 200,
                    "sumGross": "19.90",
                    "contact": {"name": "Anderes Unternehmen"},
                },
            ]
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    inv = InvoiceClient(SevdeskConnection(client=client, config=AppConfig()))

    by_order, order_days = inv.search_invoice_summaries("20522")
    by_name, name_days = inv.search_invoice_summaries("felix griesbach")
    by_invoice, invoice_days = inv.search_invoice_summaries("RE-300")

    assert order_days == 100
    assert name_days == 100
    assert invoice_days == 100
    assert [row.id for row in by_order] == ["3"]
    assert [row.id for row in by_name] == ["3"]
    assert [row.id for row in by_invoice] == ["3"]


def test_invoice_client_search_expands_to_next_100_day_window_when_needed() -> None:
    today = date.today()
    first_page = {
        "objects": [
            {
                "id": 9,
                "invoiceNumber": "RE-009",
                "invoiceDate": (today - timedelta(days=5)).isoformat(),
                "status": 200,
                "sumGross": "10.00",
                "contact": {"name": "Nah GmbH"},
            },
            {
                "id": 8,
                "invoiceNumber": "RE-008",
                "invoiceDate": (today - timedelta(days=130)).isoformat(),
                "status": 200,
                "sumGross": "10.00",
                "customerInternalNote": "20599",
                "contact": {"name": "Weiter GmbH", "surename": "Anna", "familyname": "Alt"},
            },
        ]
    }
    second_page = {"objects": []}

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        return httpx.Response(200, json=first_page if offset == 0 else second_page)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    inv = InvoiceClient(SevdeskConnection(client=client, config=AppConfig()))

    rows, searched_days = inv.search_invoice_summaries("20599")

    assert searched_days == 200
    assert [row.id for row in rows] == ["8"]


def test_invoice_client_search_matches_reverse_name_order_and_umlaut_variants() -> None:
    today = date.today()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "objects": [
                    {
                        "id": 12,
                        "invoiceNumber": "RE-012",
                        "invoiceDate": today.isoformat(),
                        "status": 200,
                        "sumGross": "20.00",
                        "contact": {
                            "name": "Staufner Böhmische",
                            "surename": "Karl",
                            "familyname": "Bogner",
                        },
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    inv = InvoiceClient(SevdeskConnection(client=client, config=AppConfig()))

    reverse_rows, reverse_days = inv.search_invoice_summaries("Bogner Karl")
    umlaut_rows, umlaut_days = inv.search_invoice_summaries("Staufner Boehmische")

    assert reverse_days == 100
    assert umlaut_days == 100
    assert [row.id for row in reverse_rows] == ["12"]
    assert [row.id for row in umlaut_rows] == ["12"]


def test_invoice_summary_coerces_null_invoice_number() -> None:
    summary = InvoiceSummary.model_validate(
        {
            "id": "41",
            "invoiceNumber": None,
            "status": 200,
        }
    )

    assert summary.invoice_number == ""
    row = summary.as_table_row()
    assert row["sevDesk"] == "—"


def test_invoice_summary_extracts_country_from_string_code() -> None:
    summary = InvoiceSummary.from_api_object(
        {
            "id": "52",
            "invoiceNumber": "R-52",
            "status": 200,
            "addressCountryCode": "de",
        }
    )

    assert summary.display_country == "DE"


def test_invoice_summary_wix_order_column_uses_order_number_not_uuid() -> None:
    numeric_ref = InvoiceSummary.model_validate(
        {
            "id": "77",
            "invoiceNumber": "R-77",
            "order_reference": "WIX-10023",
        }
    )
    uuid_ref = InvoiceSummary.model_validate(
        {
            "id": "78",
            "invoiceNumber": "R-78",
            "order_reference": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        }
    )

    assert numeric_ref.as_table_row()["WIX"] == "10023"
    assert uuid_ref.as_table_row()["WIX"] == "—"
