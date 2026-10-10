from __future__ import annotations

import json

from xw_office.services.drucke.service import OffeneDruckeService
from xw_office.services.drucke.xw_flow_client import FlowPrintCase


class _Repo:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value: str) -> None:
        self.values[key] = value


class _Secrets:
    def get_secret(self, _key: str) -> str:
        return ""


class _Flow:
    def __init__(self) -> None:
        self.status_updates: list[tuple[str, bool]] = []
        self.synced: list[object] = []

    def is_configured(self) -> bool:
        return True

    def fetch_open_cases(self) -> list[FlowPrintCase]:
        return [FlowPrintCase(id="flow-print", title="Partitur", body_text="A4 doppelseitig", source_url="", created_at="2026-10-10T10:00:00Z")]

    def set_status(self, case_id: str, *, completed: bool) -> None:
        self.status_updates.append((case_id, completed))

    def sync_print_email_cases(self, cases: list[object]) -> None:
        self.synced = cases

    def fetch_completed_email_request_ids(self) -> set[str]:
        return set()


def test_flow_print_is_visible_and_completion_is_mirrored() -> None:
    flow = _Flow()
    service = OffeneDruckeService(_Repo(), _Secrets(), flow)  # type: ignore[arg-type]

    cases = service.refresh_from_graph()

    assert [(case.id, case.title) for case in cases] == [("flow:flow-print", "Partitur")]
    service.mark_done("flow:flow-print", done=True)
    assert flow.status_updates == [("flow-print", True)]
    assert service.open_count() == 0


def test_completed_email_request_id_uses_the_shared_deterministic_namespace() -> None:
    service = OffeneDruckeService(_Repo(), _Secrets())  # type: ignore[arg-type]
    assert str(service._email_request_id("mail-id")) == str(service._email_request_id("mail-id"))
    assert str(service._email_request_id("mail-id")) != str(service._email_request_id("other-mail-id"))
