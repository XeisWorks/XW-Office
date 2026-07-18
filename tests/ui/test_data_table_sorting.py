from __future__ import annotations

from PySide6.QtCore import Qt

from xw_studio.ui.widgets.data_table import DataTable


def test_data_table_uses_explicit_sort_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    table = DataTable(["Label", "Amount"])
    qtbot.addWidget(table)
    table.set_data(
        [
            {"Label": "small", "Amount": "EUR 10.00", "__sort__Amount": 10.0},
            {"Label": "large", "Amount": "EUR 2.00", "__sort__Amount": 2.0},
        ]
    )

    table.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    assert table.model().index(0, 0).data() == "large"
