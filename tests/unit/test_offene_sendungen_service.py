from __future__ import annotations

import json
from typing import Any

from xw_studio.services.sendungen.service import OffeneSendungenService


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


def _message(msg_id: str, subject: str, preview: str = "") -> dict[str, Any]:
    return {
        "id": msg_id,
        "receivedDateTime": "2026-06-30T10:00:00Z",
        "subject": subject,
        "bodyPreview": preview,
        "body": {"content": preview, "contentType": "text"},
        "from": {"emailAddress": {"address": "kunde@example.test"}},
        "conversationId": f"thread-{msg_id}",
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


def test_refresh_count_from_graph_silent_reads_and_filters_candidates(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [
                _message("m1", "Versand bitte prüfen", "Bestellung 20868"),
                _message("m2", "Normale Rückfrage", "ohne Lieferhinweis"),
            ]

    monkeypatch.setattr("xw_studio.services.sendungen.service.GraphMailClient", _GraphClient)
    service = OffeneSendungenService(_Repo(), _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    cases = service.load_open_cases()
    assert [case.id for case in cases] == ["m1"]
