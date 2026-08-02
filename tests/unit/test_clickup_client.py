"""Tests for ClickUp client."""
from __future__ import annotations

import httpx
import pytest

from xw_office.services.clickup.client import ClickUpClient


class _SecretServiceStub:
    def __init__(self, token: str = "") -> None:
        self._token = token

    def get_secret(self, key: str) -> str:
        if key == "CLICKUP_API_TOKEN":
            return self._token
        return ""


def test_has_credentials_reflects_secret() -> None:
    assert ClickUpClient(_SecretServiceStub("token-123")).has_credentials() is True
    assert ClickUpClient(_SecretServiceStub("")).has_credentials() is False


def test_create_task_requires_list_id() -> None:
    client = ClickUpClient(_SecretServiceStub("token-123"))

    with pytest.raises(ValueError, match="Listen-ID"):
        client.create_task("Neue Aufgabe")


def test_create_task_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _DummyClient:
        def __enter__(self) -> _DummyClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            request = httpx.Request("POST", url, json=json, headers=headers)
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "task-1",
                    "name": "Neue Aufgabe",
                    "url": "https://app.clickup.com/t/task-1",
                    "status": {"status": "open"},
                },
            )

    monkeypatch.setattr(
        "xw_office.services.clickup.client.httpx.Client",
        lambda timeout: _DummyClient(),
    )

    client = ClickUpClient(_SecretServiceStub("token-123"))
    task = client.create_task(
        "Neue Aufgabe",
        description="Beschreibung",
        list_id="list-42",
        priority=2,
        tags=["office"],
    )

    assert task.id == "task-1"
    assert captured["url"] == "https://api.clickup.com/api/v2/list/list-42/task"
    assert captured["json"] == {
        "name": "Neue Aufgabe",
        "description": "Beschreibung",
        "priority": 2,
        "tags": ["office"],
    }
    assert captured["headers"] == {
        "Authorization": "token-123",
        "Content-Type": "application/json",
    }
