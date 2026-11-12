from __future__ import annotations

from PySide6.QtCore import QPersistentModelIndex, Qt

from xw_office.ui.widgets.data_table import DataTable, SimpleTableModel


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


def test_simple_table_model_accepts_persistent_indexes() -> None:
    model = SimpleTableModel(["Label"])
    model.set_data([{"Label": "kept"}])
    index = QPersistentModelIndex(model.index(0, 0))

    assert model.rowCount(index) == 1
    assert model.columnCount(index) == 1
    assert model.data(index) == "kept"
