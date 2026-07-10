from __future__ import annotations

import json
from typing import Any

import pytest

from xw_studio.services.sendungen.service import OffeneSendungenService, SendungProductLine


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
) -> dict[str, Any]:
    return {
        "id": msg_id,
        "receivedDateTime": "2026-06-30T10:00:00Z",
        "subject": subject,
        "bodyPreview": preview,
        "body": {"content": preview, "contentType": "text"},
        "from": {"emailAddress": {"address": "kunde@example.test"}},
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

    monkeypatch.setattr("xw_studio.services.sendungen.service.GraphMailClient", _GraphClient)
    repo = _Repo()
    repo.values["daily_business.offene_sendungen.cases.raw_graph"] = json.dumps(
        [_message("m1", "Versand bitte an neue Adresse", "Bestellung 20868")]
    )

    service = OffeneSendungenService(repo, _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    assert service.open_count() == 1


def test_refresh_count_from_graph_silent_applies_keywords_and_outlook_flag(monkeypatch) -> None:
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

    monkeypatch.setattr("xw_studio.services.sendungen.service.GraphMailClient", _GraphClient)
    service = OffeneSendungenService(_Repo(), _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    cases = service.load_open_cases()
    assert [case.id for case in cases] == ["m1"]


def test_mark_done_sets_outlook_flag_before_local_done(monkeypatch) -> None:
    patched: list[str] = []

    class _GraphClient:
        def __init__(self, **kwargs: object) -> None:
            assert "Mail.ReadWrite" in kwargs["scopes"]  # type: ignore[operator]

        def mark_message_followup_complete(self, message_id: str) -> None:
            patched.append(message_id)

    monkeypatch.setattr("xw_studio.services.sendungen.service.GraphMailClient", _GraphClient)
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

    monkeypatch.setattr("xw_studio.services.sendungen.service.GraphMailClient", _GraphClient)
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
        products=[SendungProductLine(quantity="1", name="Musikbuch Alpen", sku="XW-42")],
        manual_text="Danke fuer die Bestellung.",
        summary="Kurzfassung",
    )

    import fitz

    with fitz.open(path) as doc:
        text = "\n".join(page.get_text() for page in doc)
    assert "LIEFERSCHEIN" in text
    assert "Musikbuch Alpen" in text
    assert "XeisWorks" in text
