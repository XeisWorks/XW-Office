from __future__ import annotations

from pathlib import Path
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from PySide6.QtWidgets import QDialog, QMessageBox

from xw_office.services.digital_licenses import DigitalLicenseCase
from xw_office.services.digital_licenses import DigitalLicenseService
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
