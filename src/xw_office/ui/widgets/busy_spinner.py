"""Modern arc-style busy spinner and a search status banner."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class BusySpinner(QWidget):
    """Rotating arc spinner; the timer only runs while the widget is visible."""

    def __init__(self, parent: QWidget | None = None, *, size: int = 18, color: str = "#1d4ed8") -> None:
        super().__init__(parent)
        self._angle = 0
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)

    def _advance(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def showEvent(self, event: object) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)  # type: ignore[arg-type]

    def hideEvent(self, event: object) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(2.0, self.width() / 8)
        inset = width / 2 + 1
        rect = QRectF(inset, inset, self.width() - 2 * inset, self.height() - 2 * inset)
        track = QColor(self._color)
        track.setAlpha(40)
        pen = QPen(track, width)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        pen = QPen(self._color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, -self._angle * 16, -100 * 16)


class SearchStatusBanner(QWidget):
    """Strip below the search field: busy state while searching, result hint afterwards."""

    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchStatusBanner")
        self.setStyleSheet(
            "#searchStatusBanner { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; }"
            "#searchStatusBanner QLabel { color: #1e3a8a; background: transparent; }"
            "#searchStatusBanner QPushButton { color: #1d4ed8; border: none; font-weight: 600; padding: 2px 8px; }"
            "#searchStatusBanner QPushButton:hover { text-decoration: underline; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)
        self._spinner = BusySpinner(self)
        self._label = QLabel("")
        self._reset = QPushButton("✕ Suche zurücksetzen")
        self._reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset.clicked.connect(self.reset_requested)
        layout.addWidget(self._spinner)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._reset)
        self.hide()

    def show_busy(self, message: str) -> None:
        self._spinner.show()
        self._label.setText(message)
        self.show()

    def show_result(self, message: str) -> None:
        self._spinner.hide()
        self._label.setText(message)
        self.show()
