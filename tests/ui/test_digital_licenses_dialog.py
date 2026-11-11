from __future__ import annotations

from threading import Event
from pathlib import Path
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from PySide6.QtWidgets import QDialog, QMessageBox

from xw_office.services.digital_licenses import (
    DigitalLicenseCase,
    DigitalLicenseLine,
    DigitalLicenseService,
)
from xw_office.ui.modules.rechnungen.digital_licenses_dialog import DigitalLicensesDialog


class _FakeDigitalLicenseService:
    def __init__(self) -> None:
        self.case = DigitalLicenseCase(
            invoice_id="inv-1",
            invoice_number="RE-1",
            order_reference="12345",
            customer_name="Anna Example",
            customer_email="anna@example.test",
            lines=[],
            state="DRAFT_READY",
        )
        self.mark_done_calls = 0

    def list_open_cases(self, *, limit: int = 100, use_cache: bool = False) -> list[DigitalLicenseCase]:
        del limit, use_cache
        return [self.case] if self.case is not None else []

    def open_count(self, *, limit: int = 30, use_cache: bool = True) -> int:
        del limit, use_cache
        return 1 if self.case is not None else 0

    def mark_done(self, case: DigitalLicenseCase) -> None:
        assert case is self.case
        self.mark_done_calls += 1
        self.case = None


class _FakeContainer:
    def __init__(self, service: _FakeDigitalLicenseService) -> None:
        self._service = service

    def resolve(self, service_type: object) -> object:
        if service_type is DigitalLicenseService:
            return self._service
        raise KeyError(str(service_type))


def test_mark_done_closes_dialog_when_queue_is_empty(qtbot: object, monkeypatch) -> None:
    service = _FakeDigitalLicenseService()
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog._mark_selected_done()  # noqa: SLF001

    qtbot.waitUntil(lambda: service.mark_done_calls == 1, timeout=2000)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000)
    assert dialog.open_count() == 0


def test_dialog_stays_open_until_fulfillment_write_finishes(qtbot: QtBot, monkeypatch) -> None:
    service = _FakeDigitalLicenseService()
    entered, release = Event(), Event()
    mark_done = service.mark_done

    def blocked_mark_done(case: DigitalLicenseCase) -> None:
        entered.set()
        assert release.wait(3)
        mark_done(case)

    monkeypatch.setattr(service, "mark_done", blocked_mark_done)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001
    try:
        dialog._mark_selected_done()  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=2000)

        dialog.reject()
        dialog.close()
        assert dialog.isVisible()

        release.set()
        qtbot.waitUntil(
            lambda: dialog.result() == QDialog.DialogCode.Accepted,
            timeout=2000,
        )
    finally:
        release.set()

    assert service.mark_done_calls == 1
    assert dialog.open_count() == 0


def test_late_case_load_is_ignored_after_dialog_close(qtbot: QtBot) -> None:
    service = _FakeDigitalLicenseService()
    entered, release = Event(), Event()

    def blocked_list_open_cases(**_kwargs: object) -> list[DigitalLicenseCase]:
        entered.set()
        assert release.wait(3)
        return [service.case]

    service.list_open_cases = blocked_list_open_cases  # type: ignore[method-assign]
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        dialog.reject()
        assert not dialog.isVisible()

        release.set()
        qtbot.waitUntil(lambda: dialog._load_worker is None, timeout=2000)  # noqa: SLF001
    finally:
        release.set()

    assert dialog._cases == []  # noqa: SLF001


def test_unknown_mark_done_payload_reloads_without_synchronous_count(
    qtbot: object, monkeypatch: MonkeyPatch
) -> None:
    service = _FakeDigitalLicenseService()
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001


def test_open_count_uses_loaded_cases(qtbot: object, monkeypatch: MonkeyPatch) -> None:
    service = _FakeDigitalLicenseService()
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001
    monkeypatch.setattr(
        service,
        "open_count",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("sync read")),
    )

    assert dialog.open_count() == 1
    monkeypatch.setattr(
        service,
        "open_count",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("sync read")),
    )

    dialog._on_mark_done_finished(object())  # noqa: SLF001

    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001


def test_print_path_persistence_runs_in_worker_and_updates_captured_line(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from threading import Event

    service = _FakeDigitalLicenseService()
    line = DigitalLicenseLine(
        sku="SKU-1", name="Noten", quantity=1, missing_print_file=True
    )
    service.case.lines = [line]
    path = tmp_path / "noten.pdf"
    path.write_bytes(b"%PDF-test")
    entered, release = Event(), Event()
    saved: list[tuple[str, str]] = []

    def save_print_path(sku: str, print_path: str) -> None:
        saved.append((sku, print_path))
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(service, "apply_print_path", save_print_path, raising=False)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.digital_licenses_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "PDF (*.pdf)"),
    )
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001
    try:
        dialog._pick_missing_pdf()  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=2000)
        assert dialog._draft_worker is not None  # noqa: SLF001
        assert dialog._draft_worker.isRunning()  # noqa: SLF001
        assert not dialog._list.isEnabled()  # noqa: SLF001
        assert line.missing_print_file
        release.set()
        qtbot.waitUntil(lambda: dialog._draft_worker is None, timeout=2000)  # noqa: SLF001
    finally:
        release.set()

    assert saved == [("SKU-1", str(path))]
    assert line.print_file_path == str(path)
    assert not line.missing_print_file


def test_print_path_file_check_runs_in_worker_without_blocking_ui(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from threading import Event
    from PySide6.QtCore import QTimer

    service = _FakeDigitalLicenseService()
    line = DigitalLicenseLine(
        sku="SKU-1", name="Noten", quantity=1, missing_print_file=True
    )
    service.case.lines = [line]
    path = tmp_path / "noten.pdf"
    entered, release = Event(), Event()
    saved: list[tuple[str, str]] = []

    def save_print_path(sku: str, print_path: str) -> None:
        saved.append((sku, print_path))

    monkeypatch.setattr(service, "apply_print_path", save_print_path, raising=False)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.digital_licenses_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "PDF (*.pdf)"),
    )
    original_is_file = Path.is_file

    def blocked_is_file(candidate: Path) -> bool:
        if candidate == path:
            entered.set()
            assert release.wait(3)
            return True
        return original_is_file(candidate)

    monkeypatch.setattr(Path, "is_file", blocked_is_file)
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001
    heartbeat: list[bool] = []
    timer = QTimer(dialog)
    timer.timeout.connect(lambda: heartbeat.append(True))
    timer.start(5)
    try:
        dialog._pick_missing_pdf()  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=2000)
        qtbot.waitUntil(lambda: bool(heartbeat), timeout=1000)
        assert dialog._draft_worker is not None  # noqa: SLF001
        assert dialog._draft_worker.isRunning()  # noqa: SLF001
        assert saved == []
        assert line.missing_print_file
        release.set()
        qtbot.waitUntil(lambda: dialog._draft_worker is None, timeout=2000)  # noqa: SLF001
    finally:
        release.set()
        timer.stop()

    assert saved == [("SKU-1", str(path))]
    assert line.print_file_path == str(path)
    assert not line.missing_print_file


def test_missing_print_path_is_rejected_in_worker(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    service = _FakeDigitalLicenseService()
    line = DigitalLicenseLine(
        sku="SKU-1", name="Noten", quantity=1, missing_print_file=True
    )
    service.case.lines = [line]
    path = tmp_path / "missing.pdf"
    saved: list[tuple[str, str]] = []
    warnings: list[str] = []

    def save_print_path(sku: str, print_path: str) -> None:
        saved.append((sku, print_path))

    monkeypatch.setattr(service, "apply_print_path", save_print_path, raising=False)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.digital_licenses_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "PDF (*.pdf)"),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.digital_licenses_dialog.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    dialog = DigitalLicensesDialog(_FakeContainer(service))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 1, timeout=2000)  # noqa: SLF001

    dialog._pick_missing_pdf()  # noqa: SLF001
    qtbot.waitUntil(lambda: dialog._draft_worker is None, timeout=2000)  # noqa: SLF001

    assert saved == []
    assert warnings == ["Die ausgewaehlte Druck-PDF wurde nicht gefunden."]
    assert line.missing_print_file

def test_license_pipeline_keeps_original_customer_and_second_worker(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path,
) -> None:
    from threading import Event
    import os

    service = _FakeDigitalLicenseService()
    first = service.case
    first.state = 'PENDING_DECISION'
    second = DigitalLicenseCase(
        invoice_id='inv-2', invoice_number='RE-2', order_reference='54321',
        customer_name='Other Customer', customer_email='other@example.test', lines=[],
    )
    monkeypatch.setattr(service, 'list_open_cases', lambda **kwargs: [first, second])
    prepare_entered, prepare_release = Event(), Event()
    draft_entered, draft_release = Event(), Event()
    prepared = tmp_path / 'customer-a.pdf'
    prepare_calls, drafts = [], []

    def prepare(case: DigitalLicenseCase) -> list[Path]:
        prepare_calls.append(case)
        prepare_entered.set()
        assert prepare_release.wait(3)
        return [prepared]

    def create(case: DigitalLicenseCase, files: list[Path]) -> None:
        drafts.append((case, files))
        draft_entered.set()
        assert draft_release.wait(3)

    monkeypatch.setattr(service, 'prepare_license_files', prepare, raising=False)
    monkeypatch.setattr(service, 'create_outlook_draft', create, raising=False)
    monkeypatch.setattr(os, 'startfile', lambda _: None, raising=False)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    dialog = DigitalLicensesDialog(_FakeContainer(service))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._list.count() == 2)
    try:
        dialog._prepare_selected()
        qtbot.waitUntil(prepare_entered.is_set)
        assert not dialog._list.isEnabled()
        # Programmatic selection changes must also preserve the captured case.
        dialog._list.setCurrentRow(1)
        prepare_release.set()
        qtbot.waitUntil(draft_entered.is_set)
        qtbot.wait(30)
        assert dialog._draft_worker is not None
        assert dialog._draft_worker.isRunning()
        assert not dialog._btn_prepare.isEnabled()
        dialog._prepare_selected()
        assert prepare_calls == [first]
        assert drafts == [(first, [prepared])]
    finally:
        prepare_release.set()
        draft_release.set()
        qtbot.waitUntil(lambda: dialog._draft_worker is None)
    assert first.state == 'DRAFT_READY'
    assert second.state == 'PENDING_DECISION'
    assert not dialog._btn_done.isEnabled()
