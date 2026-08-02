from __future__ import annotations

import json
from typing import Any

from xw_office.services.transfers.service import OffeneUeberweisungenService


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
            "MS_GRAPH_TRANSFER_MAILBOX": "transfer@example.test",
            "OPENAI_API_KEY": "",
        }

    def get_secret(self, key: str) -> str:
        return self.values.get(key, "")


def _message(msg_id: str, *, flag_status: str = "notFlagged") -> dict[str, Any]:
    return {
        "id": msg_id,
        "internetMessageId": f"<{msg_id}@example.test>",
        "receivedDateTime": "2026-07-10T10:00:00Z",
        "subject": "Rechnung bitte ueberweisen",
        "bodyPreview": "Bitte zahlen",
        "body": {"content": "Bitte zahlen", "contentType": "text"},
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
            raise AssertionError("silent refresh must not fetch Graph when silent token is missing")

        def get_conversation_thread_text(self, conversation_id: str, *, days: int = 60, top: int = 20) -> str:
            del conversation_id, days, top
            return ""

    monkeypatch.setattr("xw_office.services.transfers.service.GraphMailClient", _GraphClient)

    repo = _Repo()
    repo.values["daily_business.open_transfers.raw_graph"] = json.dumps([_message("m1")])

    service = OffeneUeberweisungenService(repo, _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    assert service.open_count() == 1
    assert service.needs_interactive_graph_login() is True


def test_refresh_filters_out_complete_flag(monkeypatch) -> None:
    calls = {"threads": 0}

    class _GraphClient:
        init_kwargs: list[dict[str, object]] = []

        def __init__(self, **_kwargs: object) -> None:
            self.init_kwargs.append(dict(_kwargs))

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [_message("m1", flag_status="notFlagged"), _message("m2", flag_status="complete")]

        def get_conversation_thread_text(self, conversation_id: str, *, days: int = 60, top: int = 20) -> str:
            del conversation_id, days, top
            calls["threads"] += 1
            return ""

    monkeypatch.setattr("xw_office.services.transfers.service.GraphMailClient", _GraphClient)

    service = OffeneUeberweisungenService(_Repo(), _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1
    ids = [case.id for case in service.load_open_cases()]
    assert ids == ["m1"]
    assert calls["threads"] == 0
    scopes = _GraphClient.init_kwargs[0]["scopes"]
    assert "Mail.Read" in scopes
    assert "Mail.ReadWrite" not in scopes


def test_refresh_counts_blank_not_completed_mail_in_transfer_mailbox(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            msg = _message("m1", flag_status="notFlagged")
            msg["subject"] = ""
            msg["bodyPreview"] = ""
            msg["body"] = {"content": "", "contentType": "text"}
            return [msg]

        def get_conversation_thread_text(self, conversation_id: str, *, days: int = 60, top: int = 20) -> str:
            raise AssertionError("silent count must not load conversation threads")

    monkeypatch.setattr("xw_office.services.transfers.service.GraphMailClient", _GraphClient)

    service = OffeneUeberweisungenService(_Repo(), _Secrets())  # type: ignore[arg-type]

    assert service.refresh_count_from_graph_silent() == 1


def test_silent_refresh_preserves_cached_cases_when_token_missing(monkeypatch) -> None:
    class _GraphClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def has_silent_token(self) -> bool:
            return False

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            raise AssertionError("silent refresh must not call Graph without token")

        def get_conversation_thread_text(self, conversation_id: str, *, days: int = 60, top: int = 20) -> str:
            raise AssertionError("silent refresh must not load conversation threads")

    monkeypatch.setattr("xw_office.services.transfers.service.GraphMailClient", _GraphClient)

    repo = _Repo()
    service = OffeneUeberweisungenService(repo, _Secrets())  # type: ignore[arg-type]
    repo.values["daily_business.open_transfers.cases"] = json.dumps(
        [
            {
                "id": "cached",
                "internet_message_id": "<cached@example.test>",
                "conversation_id": "",
                "received_at": "2026-07-10T10:00:00Z",
                "sender": "x@example.test",
                "subject": "cached",
                "snippet": "",
                "body": "",
                "status": "open",
                "outlook_flag_status": "notFlagged",
            }
        ]
    )

    assert service.refresh_count_from_graph_silent() == 1


def test_mark_done_in_outlook_requires_successful_graph_patch(monkeypatch) -> None:
    class _GraphClient:
        init_kwargs: list[dict[str, object]] = []

        def __init__(self, **_kwargs: object) -> None:
            self.init_kwargs.append(dict(_kwargs))

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [_message("m1")]

        def get_conversation_thread_text(self, conversation_id: str, *, days: int = 60, top: int = 20) -> str:
            del conversation_id, days, top
            return ""

        def mark_message_followup_complete(self, message_id: str) -> None:
            raise RuntimeError(f"patch failed for {message_id}")

    monkeypatch.setattr("xw_office.services.transfers.service.GraphMailClient", _GraphClient)

    service = OffeneUeberweisungenService(_Repo(), _Secrets())  # type: ignore[arg-type]
    service.refresh_count_from_graph_silent()

    from xw_office.services.transfers.models import TransferPaymentData

    try:
        service.mark_done_in_outlook("m1", TransferPaymentData())
    except RuntimeError:
        pass

    assert [case.id for case in service.load_open_cases()] == ["m1"]
    write_scopes = _GraphClient.init_kwargs[-1]["scopes"]
    assert "Mail.ReadWrite" in write_scopes
