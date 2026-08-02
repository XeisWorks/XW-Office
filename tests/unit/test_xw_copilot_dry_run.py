"""Tests for XW-Copilot dry-run request contract execution."""
from __future__ import annotations

from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService
from xw_office.services.xw_copilot.service import XWCopilotConfig


class _ConfigServiceStub:
    def __init__(self, mode: str = "dry_run") -> None:
        self._mode = mode

    def load_config(self) -> XWCopilotConfig:
        return XWCopilotConfig(enabled=True, mode=self._mode)


def test_dry_run_accepts_supported_action() -> None:
    svc = XWCopilotDryRunService(_ConfigServiceStub())  # type: ignore[arg-type]
    response = svc.simulate_raw_request(
        """
        {
          "tenant": "xeisworks",
          "mailbox": "info@xeisworks.at",
          "action": "crm.lookup_contact",
          "payload_version": "1.0",
          "payload": {"query": "Muster"}
        }
        """
    )

    assert response.accepted is True
    assert response.action == "crm.lookup_contact"
    assert response.preview["service"] == "crm"
    assert response.errors == []


def test_dry_run_rejects_invalid_json() -> None:
    svc = XWCopilotDryRunService(_ConfigServiceStub())  # type: ignore[arg-type]
    response = svc.simulate_raw_request("{invalid")

    assert response.accepted is False
    assert response.action == "invalid_json"
    assert response.errors[0].code == "invalid_json"


def test_dry_run_rejects_unsupported_action() -> None:
    svc = XWCopilotDryRunService(_ConfigServiceStub(mode="live"))  # type: ignore[arg-type]
    response = svc.simulate_raw_request(
        """
        {
          "tenant": "xeisworks",
          "mailbox": "info@xeisworks.at",
          "action": "foo.bar",
          "payload_version": "1.0",
          "payload": {}
        }
        """
    )

    assert response.accepted is False
    assert response.mode == "live"
    assert response.errors[0].code == "unsupported_action"


def test_dry_run_rejects_missing_required_fields() -> None:
    svc = XWCopilotDryRunService(_ConfigServiceStub())  # type: ignore[arg-type]
    response = svc.simulate_raw_request('{"action": "crm.lookup_contact"}')

    assert response.accepted is False
    assert response.errors[0].code == "validation_error"
