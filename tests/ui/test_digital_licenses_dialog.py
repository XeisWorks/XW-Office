from __future__ import annotations

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
