from __future__ import annotations

import datetime as dt
import uuid

from xw_office.services.product_hub.inventory_count import (
    InventoryCountLineView,
    InventoryCountView,
    InventoryCountService,
)
from xw_office.ui.modules.products.inventory_count_dialog import InventoryCountDialog


class _Container:
    def __init__(self, service: object) -> None:
        self.service = service

    def resolve(self, service_type: object) -> object:
        assert service_type is InventoryCountService
        return self.service


def _view(*, status: str = "draft") -> InventoryCountView:
    count_id = uuid.uuid4()
    line_id = uuid.uuid4()
    return InventoryCountView(
        id=count_id,
        status=status,
        location_code="MAIN",
        started_at=dt.datetime.now(dt.timezone.utc),
        confirmed_at=None,
        baseline_source_hash="hash",
        lines=[
            InventoryCountLineView(
                id=line_id,
                variant_id=uuid.uuid4(),
                sku="XW-COUNT",
                title="Zaehltitel",
                location_code="MAIN",
                system_quantity=20,
                counted_quantity=None,
                difference=None,
                status="open",
                note="",
                movement_id=None,
            )
        ],
    )


def test_guided_inventory_dialog_records_and_confirms_all_lines(qtbot) -> None:
    started = _view()
    confirmed = _view(status="confirmed")
    confirmed = InventoryCountView(
        id=started.id,
        status=confirmed.status,
        location_code=confirmed.location_code,
        started_at=started.started_at,
        confirmed_at=dt.datetime.now(dt.timezone.utc),
        baseline_source_hash=started.baseline_source_hash,
        lines=started.lines,
    )
    calls: list[tuple[str, object]] = []

    class Service:
        def start(self):
            return started

        def record_count(self, **kwargs):
            calls.append(("record", kwargs))
            return started.lines[0]

        def confirm(self, **kwargs):
            calls.append(("confirm", kwargs))
            return confirmed

    dialog = InventoryCountDialog(_Container(Service()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001

    assert dialog._table.rowCount() == 1  # noqa: SLF001
    editor = dialog._line_edits[str(started.lines[0].id)]  # noqa: SLF001
    editor.setText("17")
    qtbot.waitUntil(dialog._confirm_button.isEnabled, timeout=1000)  # noqa: SLF001
    dialog._confirm()  # noqa: SLF001
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=1000)  # noqa: SLF001

    assert calls[0][0] == "record"
    assert calls[0][1]["counted_quantity"] == 17
    assert calls[1][0] == "confirm"
    assert dialog._table.isEnabled() is False  # noqa: SLF001
    assert "bestaetigt" in dialog._status.text()  # noqa: SLF001
