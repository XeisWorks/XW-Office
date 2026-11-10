"""Tests for the Lieferkorrektur badges/popup wiring in TagesgeschaeftView (Phase 10)."""
from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from PySide6.QtCore import QTimer

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.worker import BackgroundWorker
from xw_office.services.customer_aftercare.service import CustomerAftercareService
from xw_office.bootstrap import register_default_services
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


def test_review_alert_click_opens_dialog_prefiltered_and_updates_badges(
    qtbot: object, monkeypatch
) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)

    calls: list[dict[str, object]] = []

    def fake_open(*, initial_filter: str) -> tuple[int, int]:
        calls.append({"initial_filter": initial_filter})
        return (5, 1)

    monkeypatch.setattr(view._rechnungen_view, "open_lieferkorrekturen_dialog", fake_open)  # noqa: SLF001

    view._on_lieferkorrektur_review_alert_clicked()  # noqa: SLF001

    assert calls == [{"initial_filter": "zu_pruefen"}]
    assert view._btn_lieferkorrektur_review_alert.text() == "KORREKTUR ZU PRUEFEN (5)"  # noqa: SLF001
    assert view._btn_lieferkorrektur_due_alert.text() == "LIEFERKORREKTUR FAELLIG (1)"  # noqa: SLF001


def test_due_alert_click_opens_dialog_prefiltered_to_faellig(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)

    calls: list[dict[str, object]] = []

    def fake_open(*, initial_filter: str) -> tuple[int, int]:
        calls.append({"initial_filter": initial_filter})
        return (0, 0)

    monkeypatch.setattr(view._rechnungen_view, "open_lieferkorrekturen_dialog", fake_open)  # noqa: SLF001

    view._on_lieferkorrektur_due_alert_clicked()  # noqa: SLF001

    assert calls == [{"initial_filter": "faellig"}]
