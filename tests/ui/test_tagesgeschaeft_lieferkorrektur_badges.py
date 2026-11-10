"""Tests for the Lieferkorrektur badges/popup wiring in TagesgeschaeftView (Phase 10)."""
from __future__ import annotations

from threading import Event
import time
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.worker import BackgroundWorker
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.services.b2b_credit import B2bCreditService
from xw_office.bootstrap import register_default_services
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def _wait_embedded_rechnungen(qtbot: object, view: TagesgeschaeftView) -> None:
    qtbot.waitUntil(lambda: view._rechnungen_view is not None, timeout=3000)  # noqa: SLF001


def test_badges_result_updates_lieferkorrektur_buttons(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result(  # noqa: SLF001
        {"lieferkorrektur_review": 3, "lieferkorrektur_due": 2, "lieferkorrektur_new_review_cases": 0}
    )

    assert view._btn_lieferkorrektur_review_alert.text() == "KORREKTUR ZU PRUEFEN (3)"  # noqa: SLF001
    assert view._btn_lieferkorrektur_due_alert.text() == "LIEFERKORREKTUR FAELLIG (2)"  # noqa: SLF001
    assert not view._btn_lieferkorrektur_review_alert.isHidden()  # noqa: SLF001
    assert not view._btn_lieferkorrektur_due_alert.isHidden()  # noqa: SLF001


def test_today_open_shipments_badge_includes_unreviewed_aftercare(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result(  # noqa: SLF001
        {
            "sendungen": 4,
            "lieferkorrektur_review": 2,
            "lieferkorrektur_due": 0,
            "lieferkorrektur_new_review_cases": 0,
        }
    )

    assert view._btn_sendungen_alert.text() == "OFFENE SENDUNGEN (6)"  # noqa: SLF001


def test_sendungen_close_uses_cached_aftercare_count_and_refreshes_async(
    qtbot: object, monkeypatch
) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    view._rechnungen_view = SimpleNamespace(  # noqa: SLF001
        open_sendungen_dialog=lambda: 4,
        request_shutdown=lambda: None,
        shutdown_complete=lambda: True,
    )
    view._lieferkorrektur_review_count = 2  # noqa: SLF001
    refresh_calls: list[bool] = []
    monkeypatch.setattr(view, "_refresh_badges", lambda: refresh_calls.append(True))
    aftercare = container.resolve(CustomerAftercareService)
    monkeypatch.setattr(
        aftercare,
        "count_pending_review",
        lambda: (_ for _ in ()).throw(AssertionError("synchronous aftercare query")),
    )

    view._on_sendungen_alert_clicked()  # noqa: SLF001

    assert view._btn_sendungen_alert.text() == "OFFENE SENDUNGEN (6)"  # noqa: SLF001
    assert refresh_calls == [True]


def test_badges_result_hides_buttons_at_zero(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result({"lieferkorrektur_review": 0, "lieferkorrektur_due": 0})  # noqa: SLF001

    assert view._btn_lieferkorrektur_review_alert.isHidden()  # noqa: SLF001
    assert view._btn_lieferkorrektur_due_alert.isHidden()  # noqa: SLF001


def test_badges_result_ignores_invalid_count_payloads(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result(  # noqa: SLF001
        {
            "rechnungen": None,
            "mollie": "unbekannt",
            "gutscheine": -2,
            "sendungen": [],
            "lieferkorrektur_review": "3",
        }
    )

    assert view._btn_mollie_alert.isHidden()  # noqa: SLF001
    assert view._btn_sendungen_alert.text() == "OFFENE SENDUNGEN (3)"  # noqa: SLF001


def test_close_defers_without_blocking_until_workers_finish(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_refresh_badges", lambda: None)  # noqa: SLF001
    view.show()
    entered, release = Event(), Event()

    def blocked_job() -> None:
        entered.set()
        release.wait(3)

    worker = BackgroundWorker(blocked_job)
    view._badge_worker = worker  # noqa: SLF001
    worker.start()
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        heartbeat = Event()
        QTimer.singleShot(0, heartbeat.set)
        view.close()
        qtbot.waitUntil(heartbeat.is_set, timeout=500)
        assert not view.isHidden()
        assert view._close_timer.isActive()  # noqa: SLF001
        release.set()
        qtbot.waitUntil(view.isHidden, timeout=3000)
        assert not view._close_timer.isActive()  # noqa: SLF001
    finally:
        release.set()


def test_new_review_cases_without_active_window_does_not_start_popup_worker(qtbot: object) -> None:
    """Hybrid popup: without an active foreground window, no auto-popup fetch is started."""
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result(  # noqa: SLF001
        {"lieferkorrektur_review": 1, "lieferkorrektur_due": 0, "lieferkorrektur_new_review_cases": 1}
    )

    # Headless test runners never make a widget the OS-active window, so the
    # Hybrid guard (QApplication.activeWindow() is None) must short-circuit.
    assert view._lieferkorrektur_popup_fetch_worker is None  # noqa: SLF001
    assert view._lieferkorrektur_review_popup_open is False  # noqa: SLF001


def test_review_alert_click_opens_dialog_prefiltered_and_refreshes_badges_async(
    qtbot: object, monkeypatch
) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)

    calls: list[dict[str, object]] = []

    def fake_open(*, initial_filter: str) -> None:
        calls.append({"initial_filter": initial_filter})

    badge_refreshes: list[bool] = []
    monkeypatch.setattr(view, "_refresh_badges", lambda: badge_refreshes.append(True))  # noqa: SLF001

    monkeypatch.setattr(view._rechnungen_view, "open_lieferkorrekturen_dialog", fake_open)  # noqa: SLF001

    view._on_lieferkorrektur_review_alert_clicked()  # noqa: SLF001

    assert calls == [{"initial_filter": "zu_pruefen"}]
    assert badge_refreshes == [True]


def test_due_alert_click_opens_dialog_prefiltered_to_faellig(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)

    calls: list[dict[str, object]] = []

    def fake_open(*, initial_filter: str) -> None:
        calls.append({"initial_filter": initial_filter})

    badge_refreshes: list[bool] = []
    monkeypatch.setattr(view, "_refresh_badges", lambda: badge_refreshes.append(True))  # noqa: SLF001

    monkeypatch.setattr(view._rechnungen_view, "open_lieferkorrekturen_dialog", fake_open)  # noqa: SLF001

    view._on_lieferkorrektur_due_alert_clicked()  # noqa: SLF001

    assert calls == [{"initial_filter": "faellig"}]
    assert badge_refreshes == [True]


def test_b2b_credit_check_keeps_event_loop_responsive(qtbot: object, monkeypatch) -> None:
    entered, release, heartbeat = Event(), Event(), Event()
    load_calls: list[bool] = []

    def blocked_load(self, **_kwargs):
        load_calls.append(True)
        entered.set()
        release.wait(3)
        return []

    monkeypatch.setattr(InvoiceProcessingService, "load_invoice_summaries", blocked_load)
    monkeypatch.setattr(B2bCreditService, "evaluate", lambda _self, _summaries: [])
    monkeypatch.setattr(B2bCreditService, "count_due_plans", lambda _self: 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(TagesgeschaeftView, "_refresh_badges", lambda _self: None)

    view = TagesgeschaeftView(_build_container())
    qtbot.addWidget(view)
    view._rechnungen_view = SimpleNamespace(  # noqa: SLF001
        request_shutdown=lambda: None,
        shutdown_complete=lambda: True,
    )
    try:
        QTimer.singleShot(0, heartbeat.set)
        started = time.monotonic()
        view._on_b2b_credit_alert_clicked()  # noqa: SLF001
        assert time.monotonic() - started < 0.5
        qtbot.waitUntil(entered.is_set, timeout=2000)
        qtbot.waitUntil(heartbeat.is_set, timeout=500)
        assert view._btn_b2b_credit_alert.isEnabled() is False  # noqa: SLF001

        view._on_b2b_credit_alert_clicked()  # noqa: SLF001
        assert load_calls == [True]
        release.set()
        qtbot.waitUntil(lambda: view._b2b_credit_check_worker is None, timeout=2000)  # noqa: SLF001
        assert view._btn_b2b_credit_alert.isEnabled() is True  # noqa: SLF001
    finally:
        release.set()


def test_b2b_credit_action_keeps_event_loop_responsive_and_serialized(
    qtbot: object, monkeypatch
) -> None:
    entered, release, heartbeat = Event(), Event(), Event()
    started: list[bool] = []
    results: list[object] = []
    monkeypatch.setattr(TagesgeschaeftView, "_refresh_badges", lambda _self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    view = TagesgeschaeftView(_build_container())
    qtbot.addWidget(view)

    def blocked_write() -> object:
        started.append(True)
        entered.set()
        release.wait(3)
        return "saved"

    try:
        QTimer.singleShot(0, heartbeat.set)
        started_at = time.monotonic()
        view._start_b2b_credit_action(  # noqa: SLF001
            blocked_write,
            results.append,
            busy_text="Saving...",
            error_title="B2B",
        )
        assert time.monotonic() - started_at < 0.5
        assert view._btn_b2b_credit_alert.isEnabled() is False  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=2000)
        qtbot.waitUntil(heartbeat.is_set, timeout=500)

        view._start_b2b_credit_action(  # noqa: SLF001
            lambda: "duplicate",
            results.append,
            busy_text="Saving...",
            error_title="B2B",
        )
        assert started == [True]
        release.set()
        qtbot.waitUntil(lambda: view._b2b_credit_action_worker is None, timeout=2000)  # noqa: SLF001
        assert results == ["saved"]
        assert view._btn_b2b_credit_alert.isEnabled() is True  # noqa: SLF001
    finally:
        release.set()
