"""Tests for XW-Copilot audit log service methods."""
from __future__ import annotations

from xw_office.services.xw_copilot.service import AuditEntry, XWCopilotService


class _RepoStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


def _make_entry(action: str = "crm.lookup_contact", accepted: bool = True) -> AuditEntry:
    return AuditEntry(
        timestamp="2026-04-02 10:00:00 UTC",
        action=action,
        correlation_id="test-corr-id",
        accepted=accepted,
        mode="dry_run",
    )


def test_audit_append_and_reload() -> None:
    repo = _RepoStub()
    svc = XWCopilotService(repo)  # type: ignore[arg-type]

    entry1 = _make_entry("crm.lookup_contact", accepted=True)
    entry2 = _make_entry("invoice.read_status", accepted=False)
    svc.append_audit_entry(entry1)
    svc.append_audit_entry(entry2)

    loaded = svc.load_audit_entries()
    assert len(loaded) == 2
    # Newest first
    assert loaded[0].action == "invoice.read_status"
    assert loaded[1].action == "crm.lookup_contact"


def test_audit_clear() -> None:
    repo = _RepoStub()
    svc = XWCopilotService(repo)  # type: ignore[arg-type]
    svc.append_audit_entry(_make_entry())
    svc.clear_audit_log()
    assert svc.load_audit_entries() == []


def test_audit_max_entries_capped() -> None:
    repo = _RepoStub()
    svc = XWCopilotService(repo)  # type: ignore[arg-type]

    for i in range(110):
        svc.append_audit_entry(_make_entry(action=f"action_{i}"))

    entries = svc.load_audit_entries()
    assert len(entries) == 100


def test_audit_no_storage_is_safe() -> None:
    svc = XWCopilotService(None)
    svc.append_audit_entry(_make_entry())  # must not raise
    assert svc.load_audit_entries() == []


def test_audit_written_by_dry_run() -> None:
    from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService
    from xw_office.services.xw_copilot.service import XWCopilotConfig

    class _CfgStub:
        def load_config(self) -> XWCopilotConfig:
            return XWCopilotConfig(enabled=True, mode="dry_run")

    repo = _RepoStub()
    audit_svc = XWCopilotService(repo)  # type: ignore[arg-type]
    dry_run = XWCopilotDryRunService(
        _CfgStub(),  # type: ignore[arg-type]
        audit_service=audit_svc,
    )

    dry_run.simulate_raw_request(
        '{"tenant":"x","mailbox":"y","action":"crm.lookup_contact","payload_version":"1.0"}'
    )

    entries = audit_svc.load_audit_entries()
    assert len(entries) == 1
    assert entries[0].action == "crm.lookup_contact"
    assert entries[0].accepted is True
