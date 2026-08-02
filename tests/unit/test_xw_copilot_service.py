"""Tests for XW Copilot configuration storage service."""
from __future__ import annotations

import json

from xw_office.services.xw_copilot.service import XWCopilotConfig, XWCopilotService


class _RepoStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


def test_config_roundtrip() -> None:
    repo = _RepoStub()
    svc = XWCopilotService(repo)  # type: ignore[arg-type]

    cfg = XWCopilotConfig(
        enabled=True,
        mode="live",
        outlook_tenant_id="tenant",
        outlook_client_id="client",
        mailbox_address="info@test",
        webhook_url="https://example.test/hook",
        default_project="xw-main",
    )
    svc.save_config(cfg)

    loaded = svc.load_config()
    assert loaded == cfg


def test_templates_roundtrip() -> None:
    repo = _RepoStub()
    svc = XWCopilotService(repo)  # type: ignore[arg-type]

    templates = [
        {"name": "Antwort", "kind": "mail", "content": "Danke"},
        {"name": "Ticket", "kind": "snippet", "content": "Bitte pruefen"},
    ]
    svc.save_templates(templates)

    loaded = svc.load_templates()
    assert loaded == templates

    raw = json.loads(repo.values["xw_copilot.templates"])
    assert len(raw) == 2
