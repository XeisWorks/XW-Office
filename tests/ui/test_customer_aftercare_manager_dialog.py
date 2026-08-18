from __future__ import annotations

import uuid

from xw_office.core.config import AppConfig
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.ui.modules.rechnungen.customer_aftercare_manager_dialog import (
    CustomerAftercareManagerDialog,
)
from xw_office.ui.modules.rechnungen.customer_aftercare_review_dialog import ReviewDialogOutcome


class _FakeService:
    def __init__(self) -> None:
        self.case_id = uuid.uuid4()
        self.case = CustomerAftercareCase(
            case_type="B2B_WRONG_DELIVERY",
            ai_suggested_type="B2B_WRONG_DELIVERY",
            customer_name="Musikhaus Mueller",
            source_wix_order_number="21842",
            status="PENDING_REVIEW",
            courtesy=True,
            note="",
        )
        self.case.id = self.case_id  # type: ignore[assignment]
        self.items = [CustomerAftercareItem(role="WRONG_DELIVERED", name="Notenheft A", sku="XW-1", quantity=1)]
        self.confirm_calls: list[dict[str, object]] = []
        self.ignore_calls: list[uuid.UUID] = []
        self.resolve_calls: list[uuid.UUID] = []
        self.cancel_calls: list[uuid.UUID] = []
        self.list_calls: list[str] = []

    def count_pending_review(self) -> int:
        return 1

    def count_due(self) -> int:
        return 0

    def list_cases_for_filter(self, filter_key: str) -> list[CustomerAftercareCase]:
        self.list_calls.append(filter_key)
        return [self.case]

    def get_items(self, case_id: uuid.UUID) -> list[CustomerAftercareItem]:
        return self.items

    def confirm_case(self, case_id: uuid.UUID, *, case_type: str, courtesy: bool, note: str = "") -> None:
        self.confirm_calls.append({"case_id": case_id, "case_type": case_type, "courtesy": courtesy, "note": note})

    def ignore_case(self, case_id: uuid.UUID) -> None:
        self.ignore_calls.append(case_id)

    def mark_resolved(self, case_id: uuid.UUID) -> None:
        self.resolve_calls.append(case_id)

    def mark_cancelled(self, case_id: uuid.UUID) -> None:
        self.cancel_calls.append(case_id)


class _FakeContainer:
    config = AppConfig()

    def __init__(self, service: _FakeService) -> None:
        self._service = service

    def resolve(self, typ: object) -> object:
        if typ is CustomerAftercareService:
            return self._service
        raise KeyError(str(typ))


def _wait_loaded(qtbot: object, dialog: CustomerAftercareManagerDialog) -> None:
    qtbot.waitUntil(lambda: dialog._list.count() > 0, timeout=3000)  # noqa: SLF001


def test_dialog_loads_cases_for_initial_filter(qtbot: object) -> None:
    service = _FakeService()
    dialog = CustomerAftercareManagerDialog(_FakeContainer(service), initial_filter="zu_pruefen")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_loaded(qtbot, dialog)

    assert service.list_calls[-1] == "zu_pruefen"
    assert dialog._list.count() == 1  # noqa: SLF001


def test_selecting_case_shows_meta_and_items(qtbot: object) -> None:
    service = _FakeService()
    dialog = CustomerAftercareManagerDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_loaded(qtbot, dialog)

    dialog._list.setCurrentRow(0)  # noqa: SLF001
    qtbot.waitUntil(lambda: "Musikhaus Mueller" in dialog._meta.text(), timeout=3000)  # noqa: SLF001
    qtbot.waitUntil(lambda: "Notenheft A" in dialog._items_view.toPlainText(), timeout=3000)  # noqa: SLF001


def test_open_count_sums_pending_and_due(qtbot: object) -> None:
    service = _FakeService()
    dialog = CustomerAftercareManagerDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    assert dialog.open_count() == 1


def test_review_confirm_outcome_calls_confirm_case(qtbot: object, monkeypatch) -> None:
    service = _FakeService()
    dialog = CustomerAftercareManagerDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_loaded(qtbot, dialog)
    dialog._list.setCurrentRow(0)  # noqa: SLF001
    qtbot.waitUntil(lambda: dialog._selected_case is not None, timeout=3000)  # noqa: SLF001

    class _FakeReviewDialog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def exec(self) -> int:
            return 0

        def outcome(self) -> ReviewDialogOutcome:
            return ReviewDialogOutcome(action="confirm", case_type="B2C_WRONG_DELIVERY", courtesy=False, note="ok")

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.customer_aftercare_manager_dialog.CustomerAftercareReviewDialog",
        _FakeReviewDialog,
    )

    dialog._btn_review.click()  # noqa: SLF001
    qtbot.waitUntil(lambda: len(service.confirm_calls) == 1, timeout=3000)

    assert service.confirm_calls[0]["case_type"] == "B2C_WRONG_DELIVERY"
    assert service.confirm_calls[0]["courtesy"] is False


def test_mark_resolved_calls_service(qtbot: object) -> None:
    service = _FakeService()
    dialog = CustomerAftercareManagerDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_loaded(qtbot, dialog)
    dialog._list.setCurrentRow(0)  # noqa: SLF001
    qtbot.waitUntil(lambda: dialog._selected_case is not None, timeout=3000)  # noqa: SLF001

    dialog._btn_resolve.click()  # noqa: SLF001
    qtbot.waitUntil(lambda: len(service.resolve_calls) == 1, timeout=3000)
