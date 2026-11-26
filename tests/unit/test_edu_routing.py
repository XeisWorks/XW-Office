from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from xw_office.services.crm.edu_client import EduClient, EduInvoiceRoute
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


def test_edu_client_separates_management_and_invoice_permissions():
    keys = {
        "EDU_WIX_ORIGIN": "https://school.example.test",
        "EDU_OFFICE_SECRET": "a" * 32,
        "EDU_INVOICE_BRIDGE_ORIGIN": "https://bridge.example.test",
        "EDU_INVOICE_READ_SECRET": "b" * 32,
    }
    requests = []

    def transport(request):
        requests.append(request)
        if request.url.host == "school.example.test":
            return httpx.Response(200, json={"schools": []})
        return httpx.Response(
            200, json={"to": "school@example.test", "cc": "copy@example.test", "target": "school"}
        )

    client = EduClient(
        SimpleNamespace(get_secret=keys.get), transport=httpx.MockTransport(transport)
    )
    assert client.command("list") == {"schools": []}
    assert client.invoice_route("55") == EduInvoiceRoute(
        "school@example.test", "copy@example.test", "school"
    )
    assert requests[0].headers["x-edu-office-key"] == "a" * 32
    assert "x-api-key" not in requests[0].headers
    assert requests[1].headers["x-api-key"] == "b" * 32
    assert "x-edu-office-key" not in requests[1].headers


@pytest.mark.parametrize("is_reminder", [False, True])
def test_office_mail_routes_invoice_and_linked_reminder_to_the_order_recipient(is_reminder):
    service = object.__new__(InvoiceProcessingService)
    flags = SimpleNamespace(mail_sent=False)
    route = EduInvoiceRoute("school@example.test", "copy@example.test", "school")
    service._edu_client = Mock()
    service._edu_client.invoice_route.return_value = route
    original = {"id": "55", "invoiceType": "RE", "customerInternalNote": "EDU:order-1 | 25111"}
    reminder = {
        "id": "56",
        "invoiceType": "MA",
        "invoiceNumber": "MA-56",
        "origin": {"id": "55", "objectName": "Invoice"},
    }
    service._fetch_invoice_detail = Mock(
        side_effect=lambda invoice_id, **kwargs: reminder if str(invoice_id) == "56" else original
    )
    service._operation_claims = Mock()
    service._operation_claims.acquire.return_value = SimpleNamespace(acquired=True)
    service._mail_service = Mock()
    service._build_invoice_attachment = Mock()
    service._invoice_mail_kind = Mock(return_value="invoice")
    service._build_mail_content = Mock(return_value=("Rechnung", "Beleg anbei"))
    service._resolve_customer_email = Mock(return_value="teacher@example.test")
    service.read_fulfillment_flags = Mock(return_value=flags)
    service.write_fulfillment_flags = Mock()
    service._next_flags = Mock()
    item = reminder if is_reminder else original
    summary = InvoiceSummary(id=item["id"], invoiceNumber=item.get("invoiceNumber", "RE-55"))

    _, recipient, subject = service.send_invoice_mail_for_invoice(
        summary, recipient_override="another@example.test"
    )
    assert recipient == route.to
    assert subject == ("Mahnung MA-56" if is_reminder else "Rechnung")
    service._edu_client.invoice_route.assert_called_once_with("55")
    sent = service._mail_service.send_mail.call_args.kwargs
    assert sent["to_email"] == route.to
    assert sent["cc_email"] == route.cc
    service._resolve_customer_email.assert_not_called()


def test_office_refuses_an_edu_mail_when_routing_or_reminder_origin_is_missing():
    service = object.__new__(InvoiceProcessingService)
    service._edu_client = None
    marked = InvoiceSummary(id="1", sevdesk_reference="EDU:order-1 | 25111")
    with pytest.raises(RuntimeError, match="EDU-Rechnungsempfänger"):
        service._edu_invoice_route(marked, {})
    with pytest.raises(RuntimeError, match="Ausgangsrechnung"):
        service._edu_invoice_route(
            InvoiceSummary(id="2"),
            {"invoiceType": "MA", "origin": {"id": "2", "objectName": "Invoice"}},
        )
    assert (
        service._edu_invoice_route(InvoiceSummary(id="3"), {"customerInternalNote": "25111"})
        is None
    )
