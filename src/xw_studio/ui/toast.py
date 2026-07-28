"""Non-blocking toast notification overlay."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class Toast(QFrame):
    """Temporary notification that slides in and fades out."""

    def __init__(
        self, title: str, message: str, duration_ms: int = 4000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            Toast {
                background-color: #2a2a4a;
                border: 1px solid #c9a24d;
                border-radius: 8px;
                padding: 12px 16px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        text_layout = QHBoxLayout()
        title_label = QLabel(f"<b>{title}</b>")
        title_label.setStyleSheet("color: #e8e8e8; font-size: 13px;")
        text_layout.addWidget(title_label)

        msg_label = QLabel(message)
        msg_label.setStyleSheet("color: #a0a0b0; font-size: 12px;")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label, stretch=1)
        layout.addLayout(text_layout, stretch=1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("border: none; color: #888; font-size: 14px;")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        QTimer.singleShot(duration_ms, self.close)

    def show_at_top_right(self, parent: QWidget) -> None:
        self.setFixedWidth(380)
        self.adjustSize()
        parent_rect = parent.geometry()
        x = parent_rect.right() - self.width() - 20
        y = parent_rect.top() + 60
        self.move(x, y)
        self.show()
