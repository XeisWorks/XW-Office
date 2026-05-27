"""Dialog for OFFENE SENDUNGEN workflow (mail view, summary, label)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.container import Container
from xw_studio.services.printing.label_printer import LabelPrinter
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.services.sendungen.service import OffeneSendungenService, SendungCase


class OffeneSendungenDialog(QDialog):
    """Optimized sendungen workflow based on legacy Daily-Business behavior."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: OffeneSendungenService = container.resolve(OffeneSendungenService)
        self._cases: list[SendungCase] = []
        self._build_ui()
        self._load_cases(refresh=True)

    def _build_ui(self) -> None:
        self.setWindowTitle("OFFENE SENDUNGEN")
        self.setMinimumSize(1000, 620)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self._status = QLabel("—")
        top.addWidget(self._status, stretch=1)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(lambda: self._load_cases(refresh=True))
        top.addWidget(self._btn_refresh)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_l = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_case_selected)
        left_l.addWidget(self._list)
        split.addWidget(left)

        right = QWidget()
        right_l = QVBoxLayout(right)

        self._meta = QLabel("Keine Sendung ausgewählt")
        self._meta.setWordWrap(True)
        right_l.addWidget(self._meta)

        self._thread = QPlainTextEdit()
        self._thread.setReadOnly(True)
        self._thread.setPlaceholderText("Mailverlauf / Inhalt")
        self._thread.setMinimumHeight(170)
        right_l.addWidget(self._thread)

        row_summary = QHBoxLayout()
        self._btn_summary = QPushButton("Mit OpenAI zusammenfassen")
        self._btn_summary.clicked.connect(self._summarize_selected)
        row_summary.addWidget(self._btn_summary)
        right_l.addLayout(row_summary)

        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText("Zusammenfassung")
        self._summary.setMinimumHeight(130)
        right_l.addWidget(self._summary)

        right_l.addWidget(QLabel("Adress-Label (bearbeitbar, eine Zeile pro Zeile):"))
        self._address = QPlainTextEdit()
        self._address.setMinimumHeight(120)
        right_l.addWidget(self._address)

        row_actions = QHBoxLayout()
        self._done = QCheckBox("Als erledigt markieren")
        self._done.toggled.connect(self._toggle_done)
        row_actions.addWidget(self._done)
        row_actions.addStretch()
        self._btn_print = QPushButton("Label drucken")
        self._btn_print.clicked.connect(self._print_label)
        row_actions.addWidget(self._btn_print)
        right_l.addLayout(row_actions)

        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def open_count(self) -> int:
        return len(self._service.load_open_cases())

    def _load_cases(self, *, refresh: bool) -> None:
        if refresh:
            self._service.refresh_from_graph(lookback_days=20, max_items=150)
        self._cases = self._service.load_open_cases()
        self._list.clear()
        for case in self._cases:
            txt = f"{case.received_at[:16]} | {case.sender} | {case.subject}"
            item = QListWidgetItem(txt)
            item.setData(Qt.ItemDataRole.UserRole, case.id)
            self._list.addItem(item)
        self._status.setText(f"{len(self._cases)} offene Sendungen")
        if self._cases:
            self._list.setCurrentRow(0)
        else:
            self._meta.setText("Keine offenen Sendungen.")
            self._thread.setPlainText("")
            self._summary.setPlainText("")
            self._address.setPlainText("")

    def _current_case(self) -> SendungCase | None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._cases):
            return None
        return self._cases[idx]

    def _on_case_selected(self, _row: int) -> None:
        case = self._current_case()
        if case is None:
            return
        self._meta.setText(
            f"Von: {case.sender}\nBetreff: {case.subject}\n"
            f"Empfangen: {case.received_at}\nWix-Order-Nr: {case.order_number or 'nicht erkannt'}"
        )
        self._thread.setPlainText(case.body or case.snippet)
        self._summary.setPlainText("")
        lines = self._service.create_label_lines(case)
        self._address.setPlainText("\n".join(lines))
        self._done.blockSignals(True)
        self._done.setChecked(False)
        self._done.blockSignals(False)

    def _summarize_selected(self) -> None:
        case = self._current_case()
        if case is None:
            return
        summary = self._service.summarize_case(case)
        self._summary.setPlainText(summary)

    def _toggle_done(self, checked: bool) -> None:
        case = self._current_case()
        if case is None:
            return
        self._service.mark_done(case.id, done=checked)
        if checked:
            self._load_cases(refresh=False)

    def _print_label(self) -> None:
        case = self._current_case()
        if case is None:
            return
        lines = [ln.strip() for ln in self._address.toPlainText().splitlines() if ln.strip()]
        if not lines:
            QMessageBox.information(self, "Label", "Keine Adresszeilen vorhanden.")
            return
        try:
            printer = LabelPrinter(
                self._container.config.printing,
                print_queue=self._container.resolve(PrintQueueService),
            )
            printer.print_address(lines)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Label", f"Labeldruck fehlgeschlagen:\n\n{exc}")
            return
        QMessageBox.information(self, "Label", "Label erfolgreich an Drucker gesendet.")
