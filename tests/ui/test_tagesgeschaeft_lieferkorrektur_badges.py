"""Tests for the Lieferkorrektur badges/popup wiring in TagesgeschaeftView (Phase 10)."""
from __future__ import annotations

from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
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


def test_badges_result_hides_buttons_at_zero(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result({"lieferkorrektur_review": 0, "lieferkorrektur_due": 0})  # noqa: SLF001

    assert view._btn_lieferkorrektur_review_alert.isHidden()  # noqa: SLF001
    assert view._btn_lieferkorrektur_due_alert.isHidden()  # noqa: SLF001


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
