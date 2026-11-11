from __future__ import annotations

import pytest

from xw_office.services.mailing.graph_client import GraphMailClient
from xw_office.services.mailing.service import MailAttachment, MailDeliveryService


def test_tax_mail_delivery_requires_exact_office_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_GRAPH_TENANT_ID", "tenant-test")
    monkeypatch.setenv("MS_GRAPH_CLIENT_ID", "client-test")
    monkeypatch.setenv("MS_GRAPH_TAX_MAILBOX", "shop@xeisworks.at")

    with pytest.raises(RuntimeError, match="exakt office@xeisworks.at"):
        MailDeliveryService().send_mail(
            to_email="transfer@xeisworks.at",
            subject="[XW-PAYMENT] Test",
            text_body="synthetic",
            sender_mailbox="office@xeisworks.at",
            require_exact_sender=True,
        )


def test_tax_mail_delivery_uses_dedicated_sender_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_GRAPH_TENANT_ID", "tenant-test")
    monkeypatch.setenv("MS_GRAPH_CLIENT_ID", "client-test")
    monkeypatch.setenv("MS_GRAPH_MAILBOX", "shop@xeisworks.at")
    monkeypatch.setenv("MS_GRAPH_TAX_MAILBOX", "office@xeisworks.at")

    config = MailDeliveryService().load_graph_config(required_mailbox="office@xeisworks.at")

    assert config.mailbox_user == "office@xeisworks.at"


def test_invoice_mail_routes_through_shared_shop_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_GRAPH_TENANT_ID", "tenant-test")
    monkeypatch.setenv("MS_GRAPH_CLIENT_ID", "client-test")
    monkeypatch.setenv("MS_GRAPH_MAILBOX", "office@xeisworks.at")

    config = MailDeliveryService().load_graph_config(
        shared_sender_mailbox="shop@xeisworks.at"
    )

    assert config.mailbox_user == "shop@xeisworks.at"


def test_graph_send_payload_contains_exact_sender_and_allowlisted_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object.__new__(GraphMailClient)
    client.mailbox_user = "office@xeisworks.at"
    client._mailbox_segment = "users/office@xeisworks.at"
    client._auth_headers = lambda: {"Authorization": "Bearer synthetic"}

    captured: dict[str, object] = {}

    class Response:
        status_code = 202
        text = ""

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, object], timeout: int) -> Response:
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("xw_office.services.mailing.graph_client.requests.post", fake_post)
    client.send_mail(
        to_email="transfer@xeisworks.at",
        subject="[XW-PAYMENT] Synthetic",
        body_text="XW-Payment-Version: 1",
        attachments=[MailAttachment(filename="report.pdf", content=b"%PDF synthetic")],
    )

    assert captured["url"] == "https://graph.microsoft.com/v1.0/users/office@xeisworks.at/sendMail"
    payload = captured["json"]
    assert isinstance(payload, dict)
    message = payload["message"]
    assert isinstance(message, dict)
    assert message["from"] == {"emailAddress": {"address": "office@xeisworks.at"}}
    assert message["toRecipients"] == [{"emailAddress": {"address": "transfer@xeisworks.at"}}]
    assert message["attachments"][0]["name"] == "report.pdf"
