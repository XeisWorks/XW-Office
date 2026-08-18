from __future__ import annotations

import json
from typing import Any

import pytest

from xw_office.services.sendungen.service import OffeneSendungenService, SendungProductLine

from xw_office.services.customer_aftercare import fulfillment as aftercare_fulfillment
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem


class _Repo:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value: str) -> None:
        self.values[key] = value


class _Secrets:
    def __init__(self) -> None:
        self.values = {
            "MS_GRAPH_TENANT_ID": "tenant",
            "MS_GRAPH_CLIENT_ID": "client",
            "MS_GRAPH_MAILBOX": "mailbox@example.test",
        }

    def get_secret(self, key: str) -> str:
        return self.values.get(key, "")


def _message(
    msg_id: str,
    subject: str,
    preview: str = "",
    *,
    flag_status: str = "notFlagged",
    sender: str = "kunde@example.test",
) -> dict[str, Any]:
    return {
        "id": msg_id,
        "receivedDateTime": "2026-06-30T10:00:00Z",
        "subject": subject,
        "bodyPreview": preview,
        "body": {"content": preview, "contentType": "text"},
        "from": {"emailAddress": {"address": sender}},
        "conversationId": f"thread-{msg_id}",
        "flag": {"flagStatus": flag_status},
    }


def test_refresh_count_from_graph_silent_uses_cache_without_silent_token(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return False

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            raise AssertionError("silent refresh must not start Graph reads without silent token")

    monkeypatch.setattr("xw_office.services.sendungen.service.GraphMailClient", _GraphClient)
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases.raw_graph"] = json.dumps(
        [_message("m1", "Versand bitte an neue Adresse", "Bestellung 20868")]
    )

    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    assert service.open_count() == 1


def test_refresh_count_from_graph_silent_uses_legacy_inbox_scope_and_outlook_flag(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [
                _message("m1", "Versand bitte prüfen", "Bestellung 20868"),
                _message("m2", "Normale Rückfrage", "ohne Lieferhinweis"),
                _message("m3", "Shipment vorbereiten", flag_status="complete"),
            ]

    monkeypatch.setattr("xw_office.services.sendungen.service.GraphMailClient", _GraphClient)
    service = OffeneSendungenService(_Repo(), _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 2
    cases = service.load_open_cases()
    assert [case.id for case in cases] == ["m1", "m2"]


def test_refresh_count_from_graph_silent_excludes_legacy_system_messages(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [
                _message("m1", "Neue Bestellung 21029", sender="office@xeisworks.at"),
                _message("m2", "Your order was placed", sender="no-reply@mystore.wix.com"),
                _message("m3", "AW: Ihre Rechnung RE-262067", sender="office@xeisworks.at"),
            ]

    monkeypatch.setattr("xw_office.services.sendungen.service.GraphMailClient", _GraphClient)
    service = OffeneSendungenService(_Repo(), _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    assert [case.id for case in service.load_open_cases()] == ["m3"]


def test_mark_done_sets_outlook_flag_before_local_done(monkeypatch) -> None:
    patched: list[str] = []

    class _GraphClient:
        def __init__(self, **kwargs: object) -> None:
            assert "Mail.ReadWrite" in kwargs["scopes"]  # type: ignore[operator]

        def mark_message_followup_complete(self, message_id: str) -> None:
            patched.append(message_id)

    monkeypatch.setattr("xw_office.services.sendungen.service.GraphMailClient", _GraphClient)
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases"] = json.dumps(
        [
            {
                "id": "m1",
                "received_at": "2026-06-30T10:00:00Z",
                "sender": "kunde@example.test",
                "subject": "Versand Bestellung 20868",
                "snippet": "",
                "body": "",
                "thread_id": "thread-m1",
                "order_number": "20868",
            }
        ]
    )
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]

    service.mark_done("m1", done=True)

    assert patched == ["m1"]
    assert service.open_count() == 0


def test_mark_done_keeps_case_open_when_outlook_flag_fails(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def mark_message_followup_complete(self, _message_id: str) -> None:
            raise RuntimeError("Graph PATCH failed")

    monkeypatch.setattr("xw_office.services.sendungen.service.GraphMailClient", _GraphClient)
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases"] = json.dumps(
        [
            {
                "id": "m1",
                "received_at": "2026-06-30T10:00:00Z",
                "sender": "kunde@example.test",
                "subject": "Versand Bestellung 20868",
                "snippet": "",
                "body": "",
                "thread_id": "thread-m1",
                "order_number": "20868",
            }
        ]
    )
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Graph PATCH failed"):
        service.mark_done("m1", done=True)

    assert service.open_count() == 1


def test_extract_case_details_fallback_reads_address_and_products() -> None:
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases"] = json.dumps(
        [
            {
                "id": "m1",
                "received_at": "2026-06-30T10:00:00Z",
                "sender": "kunde@example.test",
                "subject": "Bestellung 20868",
                "snippet": "",
                "body": (
                    "Versandadresse:\n"
                    "Max Muster\n"
                    "Hauptstrasse 1\n"
                    "1010 Wien\n"
                    "AT\n\n"
                    "2x Musikbuch Alpen\n"
                    "SKU: XW-42"
                ),
                "thread_id": "thread-m1",
                "order_number": "20868",
            }
        ]
    )
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]
    service._secrets.values["OPENAI_API_KEY"] = ""  # noqa: SLF001
    service._secrets.values["MS_GRAPH_TENANT_ID"] = ""  # noqa: SLF001

    details = service.extract_case_details("m1")

    assert details.address_lines == ["Max Muster", "Hauptstrasse 1", "1010 Wien", "AT"]
    assert details.products[0].quantity == "2"
    assert details.products[0].name == "Musikbuch Alpen"


def test_create_manual_case_is_idempotent_and_stores_manual_fields() -> None:
    repo = _Repo()
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]

    first = service.create_manual_case(
        case_id="lieferkorrektur-abc",
        subject="Lieferkorrektur 21842",
        note="Kostenlose Nachlieferung zu Bestellung 21842 — Lieferkorrektur, nicht verrechnen.",
        address_lines=["Max Muster", "Hauptstrasse 1", "1010 Wien"],
        products=[SendungProductLine(quantity="1", name="Notenheft B", sku="XW-2")],
    )
    again = service.create_manual_case(
        case_id="lieferkorrektur-abc", subject="anderer titel", note="anderer text"
    )

    assert first.id == again.id == "lieferkorrektur-abc"
    assert again.subject == "Lieferkorrektur 21842"  # first call wins, no overwrite
    manual = service.load_manual_fields("lieferkorrektur-abc")
    assert manual["address_lines"] == ["Max Muster", "Hauptstrasse 1", "1010 Wien"]
    assert manual["products"][0]["name"] == "Notenheft B"
    assert service.open_count() == 1


def test_refresh_from_graph_preserves_manual_cases(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [_message("m1", "Versand bitte prüfen", "Bestellung 20868")]

    monkeypatch.setattr("xw_office.services.sendungen.service.GraphMailClient", _GraphClient)
    repo = _Repo()
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]
    service.create_manual_case(case_id="lieferkorrektur-xyz", subject="Lieferkorrektur", note="note")

    service.refresh_from_graph()

    cases = service.load_open_cases()
    assert {case.id for case in cases} == {"m1", "lieferkorrektur-xyz"}

    # Refreshing again must not duplicate the manual case.
    service.refresh_from_graph()
    assert [case.id for case in service.load_open_cases()].count("lieferkorrektur-xyz") == 1


def test_customer_aftercare_fulfillment_helpers_build_expected_note_and_lines() -> None:
    case = CustomerAftercareCase(
        case_type="B2B_MISSING_ITEMS", source_wix_order_number="21842"
    )
    items = [
        CustomerAftercareItem(role="MISSING_TO_SEND", name="Notenheft B", sku="XW-2", quantity=1),
        CustomerAftercareItem(role="WRONG_DELIVERED", name="Notenheft A", sku="XW-1", quantity=2),
    ]

    note = aftercare_fulfillment.replacement_shipment_note(case)
    lines = aftercare_fulfillment.missing_items_as_product_lines(items)

    assert "Kostenlose Nachlieferung zu Bestellung 21842" in note
    assert "nicht verrechnen" in note
    assert len(lines) == 1
    assert lines[0].name == "Notenheft B"
    assert lines[0].free_delivery is True
    assert lines[0].no_return_required is True


def test_manual_fields_are_used_for_label_lines() -> None:
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases"] = json.dumps(
        [
            {
                "id": "m1",
                "received_at": "2026-06-30T10:00:00Z",
                "sender": "kunde@example.test",
                "subject": "Bestellung 20868",
                "snippet": "",
                "body": "alte adresse",
                "thread_id": "thread-m1",
                "order_number": "20868",
            }
        ]
    )
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]
    service._secrets.values["MS_GRAPH_TENANT_ID"] = ""  # noqa: SLF001
    case = service.load_open_cases()[0]

    service.save_manual_fields(
        "m1",
        address_lines=["Neue Person", "Neue Strasse 2", "8010 Graz"],
        products=[SendungProductLine(quantity="1", name="Buch")],
        manual_text="Bitte beilegen",
    )

    assert service.create_label_lines(case) == ["Neue Person", "Neue Strasse 2", "8010 Graz"]


def test_generate_delivery_note_pdf_contains_lieferschein_text(tmp_path, monkeypatch) -> None:
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases"] = json.dumps(
        [
            {
                "id": "m1",
                "received_at": "2026-06-30T10:00:00Z",
                "sender": "kunde@example.test",
                "subject": "Bestellung 20868",
                "snippet": "",
                "body": "body",
                "thread_id": "thread-m1",
                "order_number": "20868",
            }
        ]
    )
    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]
    service._secrets.values["MS_GRAPH_TENANT_ID"] = ""  # noqa: SLF001
    monkeypatch.setattr(service, "_repo_root", lambda: tmp_path)
    (tmp_path / "icons").mkdir()

    path = service.generate_delivery_note_pdf(
        "m1",
        address_lines=["Max Muster", "Hauptstrasse 1", "1010 Wien"],
        products=[
            SendungProductLine(
                quantity="1",
                name="Musikbuch Alpen",
                sku="XW-42",
                free_delivery=False,
                delivery_price="5,90",
                no_return_required=False,
            )
        ],
        manual_text="Danke fuer die Bestellung.",
        summary="Kurzfassung",
    )

    import fitz

    with fitz.open(path) as doc:
        text = "\n".join(page.get_text() for page in doc)
    assert "LIEFERSCHEIN" in text
    assert "Musikbuch Alpen" in text
    assert "XeisWorks" in text
    assert "Lieferkosten:" in text
    assert "5,90" in text
    assert "Rücksendung eingetroffen" in text


def test_wix_shipping_address_is_preferred_and_cached_per_case() -> None:
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases"] = json.dumps(
        [
            {
                "id": "m1",
                "received_at": "2026-06-30T10:00:00Z",
                "sender": "kunde@example.test",
                "subject": "Bestellung 20868",
                "snippet": "",
                "body": "Lieferadresse:\nFalsche Adresse\nAltweg 1\n1000 Altstadt",
                "thread_id": "thread-m1",
                "order_number": "20868",
            }
        ]
    )

    class _Wix:
        def __init__(self) -> None:
            self.calls = 0

        def resolve_latest_shipping_address(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            assert kwargs["reference"] == "20868"
            return {
                "address_lines": ["Max Muster", "Neuweg 2", "1010 Wien", "Österreich"],
                "order_number": "20868",
                "source": "wix-order",
            }

    wix = _Wix()
    service = OffeneSendungenService(repo, _Secrets(), wix)  # type: ignore[arg-type]
    service._secrets.values["OPENAI_API_KEY"] = ""  # noqa: SLF001
    service._secrets.values["MS_GRAPH_TENANT_ID"] = ""  # noqa: SLF001

    first = service.extract_case_details("m1")
    second = service.extract_case_details("m1")

    assert first.address_lines[1] == "Neuweg 2"
    assert second.address_lines == first.address_lines
    assert "wix-order" in first.source
    assert wix.calls == 1
