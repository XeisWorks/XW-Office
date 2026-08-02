"""Payment-clearing UI behavior tests."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.bootstrap import register_default_services
from xw_office.ui.main_window import MainWindow
from xw_office.services.clearing.models import ClearingCandidate, MatchStatus, TransactionKind
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
