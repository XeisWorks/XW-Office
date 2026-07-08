"""Generic sortable, filterable QTableView with search integration."""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtGui import QBrush, QColor
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QHeaderView, QTableView, QWidget
from PySide6.QtCore import QItemSelectionModel


class SimpleTableModel(QAbstractTableModel):
    """Table model backed by a list of dicts."""

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = columns
        self._rows: list[dict[str, Any]] = []

    def set_data(self, rows: Sequence[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def append_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        """Append rows without clearing existing data."""
        row_list = list(rows)
        if not row_list:
            return
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n + len(row_list) - 1)
        self._rows.extend(row_list)
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        row = self._rows[index.row()]
        col = self._columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row.get(col, ""))
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = row.get(f"__tooltip__{col}")
            if tip:
                return str(tip)
            return None
        if role == Qt.ItemDataRole.ForegroundRole:
            color = row.get(f"__fg__{col}")
            if isinstance(color, str) and color.strip():
                return QBrush(QColor(color))
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            color = row.get(f"__bg__{col}")
            if isinstance(color, str) and color.strip():
                return QBrush(QColor(color))
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = row.get(f"__align__{col}")
            if align == "center":
                return int(Qt.AlignmentFlag.AlignCenter)
            if align == "right":
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            return None
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return None

    def row_data(self, row: int) -> dict[str, Any]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return {}

    def update_row_data(self, row: int, patch: dict[str, Any]) -> None:
        if not (0 <= row < len(self._rows)) or not isinstance(patch, dict) or not patch:
            return
        self._rows[row].update(patch)
        left = self.index(row, 0)
        right = self.index(row, max(0, len(self._columns) - 1))
        self.dataChanged.emit(left, right)


class DataTable(QTableView):
    """Pre-configured QTableView with sorting, alternating rows, and selection."""

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = SimpleTableModel(columns)
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self._proxy)

        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setHighlightSections(False)

    def set_data(self, rows: Sequence[dict[str, Any]]) -> None:
        self._model.set_data(rows)

    def append_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        """Append rows to the underlying model."""
        self._model.append_rows(rows)

    def set_filter(self, text: str, column: int = 0) -> None:
        self._proxy.setFilterKeyColumn(column)
        self._proxy.setFilterFixedString(text)

    def selected_row_data(self) -> dict[str, Any] | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        source_idx = self._proxy.mapToSource(indexes[0])
        return self._model.row_data(source_idx.row())

    def selected_source_rows(self) -> list[int]:
        """Selected source-model row indexes, respecting proxy sort/filter state."""
        indexes = self.selectionModel().selectedRows()
        rows: list[int] = []
        seen: set[int] = set()
        for index in indexes:
            source_idx = self._proxy.mapToSource(index)
            row = int(source_idx.row())
            if row < 0 or row in seen:
                continue
            seen.add(row)
            rows.append(row)
        return rows

    def selected_rows_data(self) -> list[dict[str, Any]]:
        """All selected row payloads in source-model order."""
        return [self._model.row_data(row) for row in self.selected_source_rows()]

    def selected_source_row(self) -> int | None:
        """0-based row index in the source model (proxy sort/filter aware)."""
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return int(self._proxy.mapToSource(indexes[0]).row())

    def update_source_row_data(self, row: int, patch: dict[str, Any]) -> None:
        self._model.update_row_data(row, patch)

    def source_rows_data(self) -> list[dict[str, Any]]:
        """Return all source-model rows in their current source order."""
        return [
            dict(self._model.row_data(row))
            for row in range(self._model.rowCount())
        ]

    def select_source_row(self, row: int) -> None:
        """Select one source-model row, respecting proxy sorting/filtering."""
        if row < 0 or row >= self._model.rowCount():
            return
        source_index = self._model.index(row, 0)
        proxy_index = self._proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return
        selection_model = self.selectionModel()
        if selection_model is None:
            return
        selection_model.select(
            proxy_index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )
        self.setCurrentIndex(proxy_index)
        self.scrollTo(proxy_index)
