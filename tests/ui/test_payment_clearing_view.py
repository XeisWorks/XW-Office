"""Payment-clearing UI behavior tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.bootstrap import register_default_services
from xw_office.ui.main_window import MainWindow
from xw_office.services.clearing.models import ClearingAnalysis, ClearingCandidate, MatchStatus, TransactionKind
from xw_office.services.clearing.service import PaymentClearingService
from xw_office.ui.modules.payment_clearing.view import PaymentClearingView


def _candidate(candidate_id: str, status: MatchStatus) -> ClearingCandidate:
    return ClearingCandidate(
        candidate_id=candidate_id,
        provider="stripe",
        kind=TransactionKind.PAYMENT,
        provider_ref=candidate_id,
        order_number="12345",
        invoice_id=1 if status == MatchStatus.READY else None,
        invoice_number="RE-1" if status == MatchStatus.READY else "",
        customer="Anna",
        amount=Decimal("19.90"),
        payment_date=datetime(2026, 5, 1, tzinfo=ZoneInfo("Europe/Vienna")),
        status=status,
        reason="test",
        selected=False,
        account_id=11,
    )


def test_select_all_only_selects_bookable_rows(qtbot: object, app_config: object) -> None:
    container = Container(app_config)  # type: ignore[arg-type]
    container.register(PaymentClearingService, lambda _c: PaymentClearingService())
    view = PaymentClearingView(container)
    qtbot.addWidget(view)
    view._candidates = [  # noqa: SLF001
        _candidate("ready", MatchStatus.READY),
        _candidate("manual", MatchStatus.MANUAL),
        _candidate("payout", MatchStatus.IMPORT_ONLY),
    ]

    view._set_all_bookable(True)  # noqa: SLF001

    selected = {row.candidate_id for row in view._candidates if row.selected}  # noqa: SLF001
    assert selected == {"ready", "payout"}


def test_default_filter_shows_all_candidates(qtbot: object, app_config: object) -> None:
    container = Container(app_config)  # type: ignore[arg-type]
    container.register(PaymentClearingService, lambda _c: PaymentClearingService())
    view = PaymentClearingView(container)
    qtbot.addWidget(view)
    view._candidates = [  # noqa: SLF001
        _candidate("ready", MatchStatus.READY),
        _candidate("manual", MatchStatus.MANUAL),
        _candidate("error", MatchStatus.ERROR),
        _candidate("done", MatchStatus.ALREADY_BOOKED),
    ]

    visible = view._filtered()  # noqa: SLF001

    assert [row.candidate_id for row in visible] == ["ready", "manual", "error", "done"]


def test_analysis_summary_shows_visible_count_and_filter(qtbot: object, app_config: object) -> None:
    container = Container(app_config)  # type: ignore[arg-type]
    container.register(PaymentClearingService, lambda _c: PaymentClearingService())
    view = PaymentClearingView(container)
    qtbot.addWidget(view)
    analysis = ClearingAnalysis(
        started_at=datetime(2026, 8, 31, tzinfo=ZoneInfo("Europe/Vienna")),
        start_date=datetime(2026, 8, 1, tzinfo=ZoneInfo("Europe/Vienna")),
        end_date=datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Vienna")),
        candidates=(
            _candidate("ready", MatchStatus.READY),
            _candidate("refund", MatchStatus.REFUND_REVIEW),
            _candidate("done", MatchStatus.ALREADY_BOOKED),
        ),
    )

    view._on_analysis(analysis)  # noqa: SLF001

    assert len(view._table.source_rows_data()) == 3  # noqa: SLF001
    assert view._summary.text() == (  # noqa: SLF001
        "3 sichtbar von 3 Vorgangen | 1 automatisch buchbar | 1 offen | Filter: Alle Vorgaenge"
    )


def test_problem_row_is_highlighted_and_explains_recheck(qtbot: object, app_config: object) -> None:
    container = Container(app_config)  # type: ignore[arg-type]
    container.register(PaymentClearingService, lambda _c: PaymentClearingService())
    view = PaymentClearingView(container)
    qtbot.addWidget(view)
    candidate = replace(
        _candidate("manual", MatchStatus.MANUAL),
        invoice_id=128476289,
        invoice_number="RE-262003",
        reason="Betrag weicht ab: Zahlung 180.00, Rechnung 144.00",
    )
    view._candidates = [candidate]  # noqa: SLF001

    view._refresh_table()  # noqa: SLF001
    row = view._table.source_rows_data()[0]  # noqa: SLF001

    assert row["__bg__Betrag"] == "#fff7d6"
    assert "RECHECK: Rechnung" in row["__tooltip__Hinweis"]


def test_month_preset_updates_date_range(qtbot: object, app_config: object) -> None:
    container = Container(app_config)  # type: ignore[arg-type]
    container.register(PaymentClearingService, lambda _c: PaymentClearingService())
    view = PaymentClearingView(container)
    qtbot.addWidget(view)

    view._month_preset.setCurrentIndex(1)  # noqa: SLF001
    expected_start = PaymentClearingView._recent_month_starts(date.today())[1]  # noqa: SLF001
    selected_start = view._start.date().toPython()  # noqa: SLF001
    selected_end = view._end.date().toPython()  # noqa: SLF001

    assert view._month_preset.count() == PaymentClearingView.MONTH_PRESET_COUNT  # noqa: SLF001
    assert selected_start == expected_start
    assert selected_end.year == expected_start.year
    assert selected_end.month == expected_start.month


def test_main_window_can_open_payment_clearing(qtbot: object, app_config: object) -> None:
    container = Container(app_config)  # type: ignore[arg-type]
    container.register(AppSignals, lambda _c: AppSignals())
    register_default_services(container)
    window = MainWindow(container)
    qtbot.addWidget(window)

    window._navigate_to(ModuleKey.CLEARING.value)  # noqa: SLF001

    qtbot.waitUntil(
        lambda: isinstance(window._pages[ModuleKey.CLEARING.value], PaymentClearingView),  # noqa: SLF001
        timeout=1000,
    )
