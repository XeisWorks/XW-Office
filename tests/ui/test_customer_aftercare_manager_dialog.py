from __future__ import annotations

import uuid
from threading import Event, get_ident

from PySide6.QtCore import QTimer

from xw_office.core.config import AppConfig
from xw_office.core.worker import BackgroundWorker
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.services.sendungen.service import OffeneSendungenService
from xw_office.ui.modules.rechnungen.customer_aftercare_manager_dialog import (
    CustomerAftercareManagerDialog,
)
from xw_office.ui.modules.rechnungen.customer_aftercare_tab import CustomerAftercareTab
from xw_office.ui.modules.rechnungen.customer_aftercare_review_dialog import ReviewDialogOutcome
from xw_office.ui.modules.rechnungen.redelivery_dialog import RedeliveryDialog


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
        self.items = [
            CustomerAftercareItem(role="WRONG_DELIVERED", name="Notenheft A", sku="XW-1", quantity=1),
            CustomerAftercareItem(role="MISSING_TO_SEND", name="Notenheft B", sku="XW-2", quantity=1),
        ]
        self.confirm_calls: list[dict[str, object]] = []
        self.ignore_calls: list[uuid.UUID] = []
        self.resolve_calls: list[uuid.UUID] = []
        self.cancel_calls: list[uuid.UUID] = []
        self.list_calls: list[str] = []
        self.read_threads: list[int] = []

    def count_pending_review(self) -> int:
        return 1

    def count_due(self) -> int:
        return 0

    def list_cases_for_filter(self, filter_key: str) -> list[CustomerAftercareCase]:
        self.read_threads.append(get_ident())
        self.list_calls.append(filter_key)
        return [self.case]

    def get_items(self, case_id: uuid.UUID) -> list[CustomerAftercareItem]:
        self.read_threads.append(get_ident())
        return self.items

    def confirm_case(self, case_id: uuid.UUID, *, case_type: str, courtesy: bool, note: str = "") -> None:
        self.confirm_calls.append({"case_id": case_id, "case_type": case_type, "courtesy": courtesy, "note": note})

    def ignore_case(self, case_id: uuid.UUID) -> None:
        self.ignore_calls.append(case_id)

    def mark_resolved(self, case_id: uuid.UUID) -> None:
        self.resolve_calls.append(case_id)

    def mark_cancelled(self, case_id: uuid.UUID) -> None:
        self.cancel_calls.append(case_id)


class _FakeOffeneSendungenService:
    def __init__(self) -> None:
        self.create_manual_case_calls: list[dict[str, object]] = []

    def create_manual_case(
        self,
        *,
        case_id: str,
        subject: str,
        note: str,
        address_lines: list[str] | None = None,
        products: list[object] | None = None,
    ) -> None:
        self.create_manual_case_calls.append(
            {"case_id": case_id, "subject": subject, "note": note, "products": products}
        )


class _FakeContainer:
    config = AppConfig()

    def __init__(self, service: _FakeService, sendungen: _FakeOffeneSendungenService | None = None) -> None:
        self._service = service
        self._sendungen = sendungen or _FakeOffeneSendungenService()

    def resolve(self, typ: object) -> object:
        if typ is CustomerAftercareService:
            return self._service
        if typ is OffeneSendungenService:
            return self._sendungen
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


def test_close_does_not_wait_for_running_worker(qtbot: object, monkeypatch) -> None:
    dialog = CustomerAftercareManagerDialog(_FakeContainer(_FakeService()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_loaded(qtbot, dialog)
    entered, release = Event(), Event()

    def blocked() -> None:
        entered.set()
        release.wait(3)

    worker = BackgroundWorker(blocked)
    dialog._action_worker = worker  # noqa: SLF001
    wait_calls: list[bool] = []
    monkeypatch.setattr(BackgroundWorker, "wait", lambda *_args: wait_calls.append(True))
    worker.start()
    qtbot.waitUntil(entered.is_set)

    dialog.close()

    assert dialog._closing is True  # noqa: SLF001
    assert wait_calls == []
    release.set()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=2000)


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


def test_prepare_nachsendung_creates_manual_case_from_missing_items(qtbot: object, monkeypatch) -> None:
    service = _FakeService()
    sendungen = _FakeOffeneSendungenService()
    dialog = CustomerAftercareManagerDialog(_FakeContainer(service, sendungen))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    _wait_loaded(qtbot, dialog)
    dialog._list.setCurrentRow(0)  # noqa: SLF001
    qtbot.waitUntil(lambda: len(dialog._selected_items) > 0, timeout=3000)  # noqa: SLF001

    class _FakeSendungenDialog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.customer_aftercare_manager_dialog.OffeneSendungenDialog",
        _FakeSendungenDialog,
    )

    dialog._btn_nachsendung.click()  # noqa: SLF001
    qtbot.waitUntil(lambda: len(sendungen.create_manual_case_calls) == 1, timeout=3000)

    call = sendungen.create_manual_case_calls[0]
    assert call["case_id"] == f"lieferkorrektur-{service.case_id}"
    product_names = [product.name for product in call["products"]]
    assert product_names == ["Notenheft B"]
    assert "nicht verrechnen" in call["note"]


def test_redelivery_tab_print_request_uses_confirmed_items_and_address(qtbot: object) -> None:
    service = _FakeService()
    service.case.status = "TRIGGERED"
    service.case.dispatch_id = f"nachlieferung-{service.case_id}"
    service.case.address_lines_json = '["Musikhaus Mueller", "Hauptstrasse 1", "1010 Wien"]'
    service.case.note = "Kostenlose Nachlieferung"
    tab = CustomerAftercareTab(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab._items_loaded_case_id == str(service.case_id), timeout=3000)  # noqa: SLF001

    request = tab._dispatch_print_request()  # noqa: SLF001

    assert request is not None
    dispatch_id, address, products, note = request
    assert dispatch_id == service.case.dispatch_id
    assert address == ["Musikhaus Mueller", "Hauptstrasse 1", "1010 Wien"]
    assert [product.name for product in products] == ["Notenheft B"]
    assert all(product.free_delivery for product in products)
    assert note == "Kostenlose Nachlieferung"
    assert tab._btn_delivery_print.isEnabled()  # noqa: SLF001
    assert tab._btn_label_print.isEnabled()  # noqa: SLF001
    assert service.read_threads
    assert all(thread_id != get_ident() for thread_id in service.read_threads)


def test_aftercare_tab_case_action_keeps_event_loop_responsive(
    qtbot: object, monkeypatch: object
) -> None:
    service = _FakeService()
    entered = Event()
    release = Event()

    def slow_resolve(case_id: uuid.UUID) -> None:
        entered.set()
        release.wait(timeout=3)
        service.resolve_calls.append(case_id)

    monkeypatch.setattr(service, "mark_resolved", slow_resolve)
    tab = CustomerAftercareTab(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab._items_loaded_case_id == str(service.case_id), timeout=3000)  # noqa: SLF001

    ticks = 0

    def heartbeat() -> None:
        nonlocal ticks
        ticks += 1

    timer = QTimer(tab)
    timer.setInterval(5)
    timer.timeout.connect(heartbeat)
    timer.start()
    try:
        tab._resolve()  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=1000)
        qtbot.wait(40)
        assert ticks > 0
        assert service.resolve_calls == []
    finally:
        release.set()
    qtbot.waitUntil(lambda: service.resolve_calls == [service.case_id], timeout=3000)
    timer.stop()


def test_aftercare_tab_discards_stale_item_result_after_selection_change(
    qtbot: object, monkeypatch: object
) -> None:
    service = _FakeService()
    second_case = CustomerAftercareCase(
        case_type="B2B_WRONG_DELIVERY",
        ai_suggested_type="B2B_WRONG_DELIVERY",
        customer_name="Second customer",
        status="WAITING",
    )
    second_case.id = uuid.uuid4()  # type: ignore[assignment]
    first_entered = Event()
    release_first = Event()

    monkeypatch.setattr(service, "list_cases_for_filter", lambda _filter: [service.case, second_case])

    def get_items(case_id: uuid.UUID) -> list[CustomerAftercareItem]:
        if case_id == service.case_id:
            first_entered.set()
            release_first.wait(timeout=3)
            return service.items
        return [CustomerAftercareItem(role="MISSING_TO_SEND", name="Second item", sku="XW-2", quantity=1)]

    monkeypatch.setattr(service, "get_items", get_items)
    tab = CustomerAftercareTab(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(tab)
    try:
        qtbot.waitUntil(first_entered.is_set, timeout=3000)
        tab._list.setCurrentRow(1)  # noqa: SLF001
        qtbot.waitUntil(
            lambda: tab._items_loaded_case_id == str(second_case.id), timeout=3000  # noqa: SLF001
        )
        release_first.set()
        qtbot.waitUntil(lambda: not tab._read_workers, timeout=3000)  # noqa: SLF001
        assert "Second item" in tab._positions.toPlainText()  # noqa: SLF001
    finally:
        release_first.set()


def test_redelivery_preview_tolerates_missing_optional_table_cells(qtbot: object, monkeypatch) -> None:
    service = _FakeService()
    dialog = RedeliveryDialog(service.case, service.items)
    qtbot.addWidget(dialog)
    dialog._table.takeItem(0, 1)  # noqa: SLF001
    dialog._table.takeItem(0, 2)  # noqa: SLF001
    dialog._table.takeItem(0, 3)  # noqa: SLF001
    messages: list[str] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.redelivery_dialog.QMessageBox.information",
        lambda _parent, _title, message: messages.append(message),
    )

    dialog._preview()  # noqa: SLF001

    assert messages and "1x Position" in messages[0]


def test_redelivery_quantities_use_bounded_numeric_editors(qtbot: object) -> None:
    source_item = CustomerAftercareItem(
        role="MISSING_TO_SEND",
        name="Originalposition",
        sku="XW-1",
        quantity=3,
        source_kind="sevdesk_invoice_position",
    )
    manual_item = CustomerAftercareItem(
        role="MISSING_TO_SEND",
        name="Manuelle Position",
        sku="XW-2",
        quantity=1,
        source_kind="manual",
    )
    dialog = RedeliveryDialog(_FakeService().case, [source_item, manual_item])
    qtbot.addWidget(dialog)

    source_quantity = dialog._table.cellWidget(0, 3)  # noqa: SLF001
    manual_quantity = dialog._table.cellWidget(1, 3)  # noqa: SLF001
    assert source_quantity.minimum() == 1
    assert source_quantity.maximum() == 3
    assert manual_quantity.maximum() == 999
    source_quantity.setValue(3)
    manual_quantity.setValue(4)

    dialog._save()  # noqa: SLF001

    outcome = dialog.outcome()
    assert outcome is not None
    assert [item.quantity for item in outcome.items] == [3, 4]
