"""Search behavior and performance tests for RechnungenView."""
from __future__ import annotations

import time

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.ui.modules.rechnungen.view import RechnungenView


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def test_search_suggestions_cover_invoice_name_order(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    view._summaries = [  # noqa: SLF001
        InvoiceSummary.model_validate(
            {
                "id": "1",
                "invoiceNumber": "RE-2026-1001",
                "contact_name": "Alpha Verlag GmbH",
                "order_reference": "12345",
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "2",
                "invoiceNumber": "RE-2026-1002",
                "contact_name": "Beta Music",
                "order_reference": "67890",
            }
        ),
    ]
    view._rebuild_search_index()  # noqa: SLF001

    by_invoice = view._invoice_search_suggestions("re-2026-1001")  # noqa: SLF001
    by_name = view._invoice_search_suggestions("alpha")  # noqa: SLF001
    by_order = view._invoice_search_suggestions("12345")  # noqa: SLF001

    assert by_invoice
    assert by_name
    assert by_order
    assert "RE-2026-1001 - Alpha Verlag GmbH" in by_invoice
    assert "RE-2026-1001 - Alpha Verlag GmbH" in by_name
    assert "RE-2026-1001 - Alpha Verlag GmbH" in by_order


def test_search_suggestions_performance_large_dataset(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    view._summaries = [  # noqa: SLF001
        InvoiceSummary.model_validate(
            {
                "id": str(i),
                "invoiceNumber": f"RE-2026-{10000 + i}",
                "contact_name": f"Firma {i}",
                "order_reference": str(900000 + i),
            }
        )
        for i in range(5000)
    ]
    view._rebuild_search_index()  # noqa: SLF001

    start = time.perf_counter()
    out = view._invoice_search_suggestions("firma 499")  # noqa: SLF001
    duration = time.perf_counter() - start

    assert out
    # Guard against UI-hang regressions: suggestion query should stay fast.
    assert duration < 0.12
