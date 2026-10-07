"""FINANZEN > Ausgabenprüfung."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QEvent, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.commission.service import format_euro_amount
from xw_office.services.expenses.reference_parser import format_expense_original_details
from xw_office.services.expenses.service import BankExpenseRow, ExpenseAuditService, ExpensePositionView
from xw_office.ui.widgets.data_table import DataTable

if False:  # pragma: no cover
    from xw_office.core.container import Container


_HEADERS = ["Datum", "Empfänger", "Zweck / Referenz", "Betrag", "Position", "Beleg"]
_ROOT = Path(__file__).resolve().parents[5]


class _PositionDelegate(QStyledItemDelegate):
    position_clicked = Signal(str, str)

    def paint(self, painter: QPainter, option: Any, index: Any) -> None:
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        positions = row.get("__positions") or []
        active = str(row.get("__position_key") or "")
        for rect, position in self._button_rects(option.rect, positions):
            color = QColor(str(position.get("color") or "#777777"))
            painter.setBrush(color if position.get("key") == active else Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(rect)
            painter.setPen(QColor("white") if position.get("key") == active else color.lighter(145))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(7 if len(str(position.get("initials") or "")) > 2 else 8)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(position.get("initials") or ""))
        painter.restore()

    def sizeHint(self, option: Any, index: Any) -> QSize:
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        return QSize(max(120, len(row.get("__positions") or []) * 34 + 8), 34)

    def editorEvent(self, event: QEvent, model: Any, option: Any, index: Any) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease or not isinstance(event, QMouseEvent):
            return False
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        for rect, position in self._button_rects(option.rect, row.get("__positions") or []):
            if rect.contains(event.position().toPoint()):
                self.position_clicked.emit(
                    str(row.get("__transaction_id") or ""), str(position.get("key") or "")
                )
                return True
        return False

    @staticmethod
    def _button_rects(cell: QRect, positions: list[dict[str, str]]) -> list[tuple[QRect, dict[str, str]]]:
        diameter = 28
        gap = 5
        left = cell.left() + 5
        top = cell.top() + max(1, (cell.height() - diameter) // 2)
        return [
            (QRect(left + index * (diameter + gap), top, diameter, diameter), position)
            for index, position in enumerate(positions)
        ]


class _DocumentDelegate(QStyledItemDelegate):
    url_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sevdesk = QIcon(str(_ROOT / "icons" / "sevdesk.png"))
        self._website = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)

    def paint(self, painter: QPainter, option: Any, index: Any) -> None:
        super().paint(painter, option, index)
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        for rect, kind, _url in self._icon_rects(option.rect, row):
            (self._sevdesk if kind == "sevdesk" else self._website).paint(painter, rect)

    def editorEvent(self, event: QEvent, model: Any, option: Any, index: Any) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease or not isinstance(event, QMouseEvent):
            return False
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        for rect, _kind, url in self._icon_rects(option.rect, row):
            if rect.contains(event.position().toPoint()) and url.startswith("https://"):
                self.url_clicked.emit(url)
                return True
        return False

    @staticmethod
    def _icon_rects(cell: QRect, row: dict[str, Any]) -> list[tuple[QRect, str, str]]:
        result: list[tuple[QRect, str, str]] = []
        left = cell.left() + 6
        top = cell.top() + max(2, (cell.height() - 22) // 2)
        for document in row.get("__documents") or []:
            result.append((QRect(left, top, 22, 22), "sevdesk", str(document.get("url") or "")))
            left += 27
        supplier_url = str(row.get("__supplier_url") or "")
        if supplier_url:
            result.append((QRect(left, top, 22, 22), "website", supplier_url))
        return result


class _RuleDialog(QDialog):
    def __init__(
        self,
        positions: list[ExpensePositionView],
        *,
        position_key: str = "",
        payee: str = "",
        iban: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zuordnungsregel merken")
        layout = QFormLayout(self)
        self.position = QComboBox()
        for item in positions:
            self.position.addItem(f"{item.initials} · {item.label}", item.key)
        wanted = self.position.findData(position_key)
        if wanted >= 0:
            self.position.setCurrentIndex(wanted)
        self.use_payee = QCheckBox(payee or "Empfänger nicht verfügbar")
        self.use_payee.setChecked(bool(payee))
        self.use_payee.setEnabled(bool(payee))
        self.use_iban = QCheckBox(self._masked_iban(iban) if iban else "IBAN nicht verfügbar")
        self.use_iban.setChecked(bool(iban))
        self.use_iban.setEnabled(bool(iban))
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("optional, z. B. musikheroes")
        layout.addRow("Position", self.position)
        layout.addRow("Empfänger exakt", self.use_payee)
        layout.addRow("IBAN exakt", self.use_iban)
        layout.addRow("Zweck enthält", self.keyword)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @staticmethod
    def _masked_iban(value: str) -> str:
        text = value.replace(" ", "")
        return f"{text[:4]} … {text[-4:]}" if len(text) > 8 else text

    def _accept_if_valid(self) -> None:
        if not (self.use_payee.isChecked() or self.use_iban.isChecked() or self.keyword.text().strip()):
            QMessageBox.information(self, "Zuordnungsregel", "Bitte mindestens ein Kriterium wählen.")
            return
        self.accept()


class _PositionDialog(QDialog):
    def __init__(self, position: ExpensePositionView | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Position bearbeiten" if position else "Position anlegen")
        layout = QFormLayout(self)
        self.key = QLineEdit(position.key if position else "")
        self.key.setEnabled(position is None)
        self.label = QLineEdit(position.label if position else "")
        self.initials = QLineEdit(position.initials if position else "")
        self.color = QLineEdit(position.color if position else "#777777")
        color_button = QPushButton("Farbe wählen")
        color_button.clicked.connect(self._choose_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color)
        color_row.addWidget(color_button)
        self.enabled = QCheckBox("aktiv")
        self.enabled.setChecked(position.enabled if position else True)
        layout.addRow("Schlüssel", self.key)
        layout.addRow("Name", self.label)
        layout.addRow("Initialen", self.initials)
        layout.addRow("Farbe", color_row)
        layout.addRow("Status", self.enabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color.text()), self)
        if color.isValid():
            self.color.setText(color.name())


class _SupplierDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lieferantenportal anlegen")
        layout = QFormLayout(self)
        self.label = QLineEdit()
        self.payee = QLineEdit()
        self.iban = QLineEdit()
        self.url = QLineEdit("https://")
        layout.addRow("Bezeichnung", self.label)
        layout.addRow("Empfänger exakt", self.payee)
        layout.addRow("IBAN optional", self.iban)
        layout.addRow("Website", self.url)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class _StandaloneRuleDialog(QDialog):
    def __init__(self, positions: list[ExpensePositionView], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zuordnungsregel anlegen")
        layout = QFormLayout(self)
        self.position = QComboBox()
        for item in positions:
            self.position.addItem(f"{item.initials} · {item.label}", item.key)
        self.label = QLineEdit()
        self.payee = QLineEdit()
        self.iban = QLineEdit()
        self.purpose = QLineEdit()
        layout.addRow("Position", self.position)
        layout.addRow("Bezeichnung", self.label)
        layout.addRow("Empfänger exakt", self.payee)
        layout.addRow("IBAN exakt", self.iban)
        layout.addRow("Zweck enthält", self.purpose)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _accept_if_valid(self) -> None:
        if not any((self.payee.text().strip(), self.iban.text().strip(), self.purpose.text().strip())):
            QMessageBox.information(self, "Zuordnungsregel", "Bitte mindestens ein Kriterium eingeben.")
            return
        self.accept()


class _AssignmentWizard(QDialog):
    def __init__(
        self,
        service: ExpenseAuditService,
        rows: list[BankExpenseRow],
        positions: list[ExpensePositionView],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._rows = rows
        self._index = 0
        self.setWindowTitle("Offene Zuordnungen prüfen")
        self.resize(720, 360)
        root = QVBoxLayout(self)
        self.progress = QLabel()
        self.details = QLabel()
        self.details.setWordWrap(True)
        root.addWidget(self.progress)
        root.addWidget(self.details, stretch=1)
        position_buttons = QHBoxLayout()
        for position in positions:
            button = QPushButton(position.initials)
            button.setToolTip(position.label)
            button.setFixedSize(54, 54)
            button.setStyleSheet(
                f"QPushButton {{ border-radius: 27px; border: 2px solid {position.color}; "
                f"color: {position.color}; font-weight: 700; }} "
                f"QPushButton:hover {{ background: {position.color}; color: white; }}"
            )
            button.clicked.connect(lambda _checked=False, key=position.key: self._assign(key))
            position_buttons.addWidget(button)
        position_buttons.addStretch()
        root.addLayout(position_buttons)
        links = QHBoxLayout()
        self.sevdesk = QPushButton("Beleg in sevDesk")
        self.website = QPushButton("Lieferantenportal")
        self.sevdesk.clicked.connect(lambda: self._open_current("sevdesk"))
        self.website.clicked.connect(lambda: self._open_current("website"))
        links.addWidget(self.sevdesk)
        links.addWidget(self.website)
        links.addStretch()
        skip = QPushButton("Später")
        skip.clicked.connect(self._next)
        close = QPushButton("Schließen")
        close.clicked.connect(self.accept)
        links.addWidget(skip)
        links.addWidget(close)
        root.addLayout(links)
        self._show_current()

    def _show_current(self) -> None:
        if self._index >= len(self._rows):
            self.accept()
            return
        row = self._rows[self._index]
        self.progress.setText(f"{self._index + 1} von {len(self._rows)}")
        docs = ", ".join(doc.document_number for doc in row.documents) or "kein sevDesk-Beleg"
        self.details.setText(
            f"<b>{row.payee or 'Unbekannter Empfänger'}</b><br>"
            f"{row.value_date:%d.%m.%Y} · {format_euro_amount(row.amount)}<br><br>"
            f"{row.purpose or 'Kein Verwendungszweck'}<br><br>Beleg: {docs}"
        )
        self.sevdesk.setEnabled(bool(row.documents))
        self.website.setEnabled(bool(row.supplier_url))

    def _assign(self, position_key: str) -> None:
        self._service.assign_transaction_position(
            transaction_id=self._rows[self._index].transaction_id,
            position_key=position_key,
        )
        self._next()

    def _next(self) -> None:
        self._index += 1
        self._show_current()

    def _open_current(self, kind: str) -> None:
        row = self._rows[self._index]
        url = row.documents[0].url if kind == "sevdesk" and row.documents else row.supplier_url
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))


class ExpenseReviewView(QWidget):
    """Review outgoing XeisWorks transactions with configurable positions."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._rows: list[BankExpenseRow] = []
        self._positions: list[ExpensePositionView] = []
        self._start = QDateEdit()
        self._end = QDateEdit()
        self._status = QLabel("Noch nicht geladen")
        self._wizard_button = QPushButton("Offene Zuordnungen prüfen")
        self._table = DataTable(_HEADERS)
        self._missing_table = DataTable(_HEADERS)
        self._position_table = DataTable(["Kürzel", "Position", "Farbe", "Aktiv"])
        self._rule_table = DataTable(["Position", "Bezeichnung", "Empfänger", "IBAN", "Zweck", "Aktiv"])
        self._supplier_table = DataTable(["Bezeichnung", "Empfänger", "IBAN", "Website", "Aktiv"])
        self._position_delegate = _PositionDelegate(self)
        self._document_delegate = _DocumentDelegate(self)
        self._build_ui()
        QTimer.singleShot(0, lambda: self._load(refresh=False))

    @property
    def service(self) -> ExpenseAuditService:
        return self._container.resolve(ExpenseAuditService)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Konto: XeisWorks"))
        controls.addWidget(QLabel("Von:"))
        self._start.setCalendarPopup(True)
        self._end.setCalendarPopup(True)
        today = datetime.now(tz=ZoneInfo("Europe/Vienna")).date()
        previous_end = today.replace(day=1) - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        self._start.setDate(QDate(previous_start.year, previous_start.month, previous_start.day))
        self._end.setDate(QDate(previous_end.year, previous_end.month, previous_end.day))
        controls.addWidget(self._start)
        controls.addWidget(QLabel("Bis:"))
        controls.addWidget(self._end)
        reload_button = QPushButton("Neu laden")
        reload_button.clicked.connect(lambda: self._load(refresh=True))
        controls.addWidget(reload_button)
        rescan_button = QPushButton("Belege neu prüfen")
        rescan_button.setToolTip("Ignoriert den Cache und prüft alle sevDesk-Belege des Zeitraums erneut.")
        rescan_button.clicked.connect(
            lambda: self._load(refresh=True, force_document_refresh=True)
        )
        controls.addWidget(rescan_button)
        controls.addStretch()
        self._wizard_button.clicked.connect(self._open_wizard)
        self._wizard_button.setVisible(False)
        self._wizard_button.setStyleSheet(
            "QPushButton { background: #c6922d; color: #111827; border-radius: 6px; "
            "font-weight: 700; padding: 7px 12px; }"
        )
        controls.addWidget(self._wizard_button)
        root.addLayout(controls)
        root.addWidget(self._status)

        tabs = QTabWidget()
        tabs.addTab(self._build_bank_tab(), "Kontobewegungen")
        tabs.addTab(self._build_missing_tab(), "Fehlende Belege")
        tabs.addTab(self._build_settings_tab(), "Einstellungen")
        root.addWidget(tabs, stretch=1)

    def _configure_expense_table(self, table: DataTable) -> None:
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setItemDelegateForColumn(4, self._position_delegate)
        table.setItemDelegateForColumn(5, self._document_delegate)
        table.setColumnWidth(4, 180)
        table.setColumnWidth(5, 150)

    def _build_bank_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._configure_expense_table(self._table)
        layout.addWidget(self._table, stretch=1)
        actions = QHBoxLayout()
        remember = QPushButton("Regel für Auswahl merken")
        remember.clicked.connect(self._remember_selected_rule)
        actions.addWidget(remember)
        actions.addStretch()
        layout.addLayout(actions)
        self._position_delegate.position_clicked.connect(self._assign_position)
        self._document_delegate.url_clicked.connect(self._open_url)
        return page

    def _build_missing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._configure_expense_table(self._missing_table)
        layout.addWidget(self._missing_table, stretch=1)
        return page

    def _build_settings_tab(self) -> QWidget:
        tabs = QTabWidget()
        positions = QWidget()
        position_layout = QVBoxLayout(positions)
        position_layout.addWidget(self._position_table)
        position_actions = QHBoxLayout()
        add_position = QPushButton("Position anlegen")
        add_position.clicked.connect(lambda: self._edit_position(None))
        edit_position = QPushButton("Auswahl bearbeiten")
        edit_position.clicked.connect(self._edit_selected_position)
        position_actions.addWidget(add_position)
        position_actions.addWidget(edit_position)
        position_actions.addStretch()
        position_layout.addLayout(position_actions)
        tabs.addTab(positions, "Positionen")

        rules = QWidget()
        rule_layout = QVBoxLayout(rules)
        rule_layout.addWidget(self._rule_table)
        rule_actions = QHBoxLayout()
        add_rule = QPushButton("Regel anlegen")
        add_rule.clicked.connect(self._add_rule)
        toggle_rule = QPushButton("Ausgewählte Regel aktivieren/deaktivieren")
        toggle_rule.clicked.connect(self._toggle_selected_rule)
        rule_actions.addWidget(add_rule)
        rule_actions.addWidget(toggle_rule)
        rule_actions.addStretch()
        rule_layout.addLayout(rule_actions)
        tabs.addTab(rules, "Zuordnungsregeln")

        suppliers = QWidget()
        supplier_layout = QVBoxLayout(suppliers)
        supplier_layout.addWidget(self._supplier_table)
        supplier_actions = QHBoxLayout()
        add_supplier = QPushButton("Lieferantenportal anlegen")
        add_supplier.clicked.connect(self._add_supplier)
        toggle_supplier = QPushButton("Auswahl aktivieren/deaktivieren")
        toggle_supplier.clicked.connect(self._toggle_selected_supplier)
        supplier_actions.addWidget(add_supplier)
        supplier_actions.addWidget(toggle_supplier)
        supplier_actions.addStretch()
        supplier_layout.addLayout(supplier_actions)
        tabs.addTab(suppliers, "Lieferantenportale")
        return tabs

    def _load(self, *, refresh: bool = True, force_document_refresh: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._positions = self.service.list_positions()
        self._status.setText("Bankbewegungen werden geladen …")
        start = cast(date, self._start.date().toPython())
        end = cast(date, self._end.date().toPython())
        self._worker = BackgroundWorker(
            lambda: self.service.list_bank_expenses(
                start=start,
                end=end,
                refresh=refresh,
                force_document_refresh=force_document_refresh,
            )
        )
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _on_loaded(self, payload: object) -> None:
        self._rows = [row for row in payload if isinstance(row, BankExpenseRow)] if isinstance(payload, list) else []
        self._populate(self._table, self._rows)
        missing = [row for row in self._rows if row.document_link_scan_complete and not row.documents]
        self._populate(self._missing_table, missing)
        incomplete = any(not row.document_link_scan_complete for row in self._rows)
        open_count = sum(not row.position_key for row in self._rows)
        suffix = " · Belegscan unvollständig" if incomplete else ""
        self._status.setText(f"{len(self._rows)} ausgehende Zahlungen · Konto XeisWorks{suffix}")
        self._wizard_button.setText(f"{open_count} offene Zuordnungen prüfen")
        self._wizard_button.setVisible(open_count > 0)
        self._refresh_settings()

    def _populate(self, table: DataTable, rows: list[BankExpenseRow]) -> None:
        position_payload = [position.__dict__ for position in self._positions]
        table.set_data(
            [
                {
                    "Datum": row.value_date.strftime("%d.%m.%Y"),
                    "Empfänger": row.payee,
                    "Zweck / Referenz": row.purpose,
                    "Betrag": format_euro_amount(row.amount),
                    "Position": "",
                    "Beleg": self._document_text(row),
                    "__transaction_id": row.transaction_id,
                    "__iban": row.iban,
                    "__payee": row.payee,
                    "__purpose": row.purpose,
                    "__positions": position_payload,
                    "__position_key": row.position_key,
                    "__documents": [document.__dict__ for document in row.documents],
                    "__supplier_url": row.supplier_url,
                    "__tooltip__Empfänger": format_expense_original_details(
                        raw_payee=row.raw_payee,
                        raw_payment_reference=row.raw_payment_reference,
                        raw_purpose=row.raw_purpose,
                        source=row.display_source,
                        confidence=row.display_confidence,
                    ),
                    "__tooltip__Zweck / Referenz": format_expense_original_details(
                        raw_payee=row.raw_payee,
                        raw_payment_reference=row.raw_payment_reference,
                        raw_purpose=row.raw_purpose,
                        source=row.display_source,
                        confidence=row.display_confidence,
                    ),
                    "__tooltip__Position": self._position_tooltip(row),
                    "__tooltip__Beleg": self._document_tooltip(row),
                    "__align__Betrag": "right",
                }
                for row in rows
            ]
        )

    @staticmethod
    def _document_text(row: BankExpenseRow) -> str:
        if row.documents:
            return "     " * len(row.documents) + ("  " if row.supplier_url else "")
        if row.supplier_url:
            return "      Lieferantenportal"
        return "nicht geprüft" if not row.document_link_scan_complete else "Link pflegen"

    @staticmethod
    def _document_tooltip(row: BankExpenseRow) -> str:
        parts = [f"sevDesk: {doc.document_number}" for doc in row.documents]
        if row.supplier_url:
            parts.append("Lieferantenportal öffnen")
        return "\n".join(parts) or (
            "Belegscan unvollständig" if not row.document_link_scan_complete else "Kein Link hinterlegt"
        )

    @staticmethod
    def _position_tooltip(row: BankExpenseRow) -> str:
        if not row.position_key:
            return "Noch nicht zugeordnet"
        suffix = f" · {row.position_rule_label}" if row.position_rule_label else ""
        return f"{row.position_source or 'zugeordnet'}{suffix}"

    def _assign_position(self, transaction_id: str, position_key: str) -> None:
        try:
            self.service.assign_transaction_position(transaction_id=transaction_id, position_key=position_key)
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)
            return
        self._rows = [
            replace(row, position_key=position_key, position_source="manual")
            if row.transaction_id == transaction_id
            else row
            for row in self._rows
        ]
        self._on_loaded(self._rows)

    def _remember_selected_rule(self) -> None:
        selected = self._table.selected_row_data()
        if not selected:
            QMessageBox.information(self, "Ausgabenprüfung", "Bitte zuerst eine Zahlung auswählen.")
            return
        dialog = _RuleDialog(
            self._positions,
            position_key=str(selected.get("__position_key") or ""),
            payee=str(selected.get("__payee") or ""),
            iban=str(selected.get("__iban") or ""),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.service.remember_position_rule(
            transaction_id=str(selected.get("__transaction_id") or ""),
            position_key=str(dialog.position.currentData()),
            payee=str(selected.get("__payee") or "") if dialog.use_payee.isChecked() else "",
            iban=str(selected.get("__iban") or "") if dialog.use_iban.isChecked() else "",
            purpose_contains=dialog.keyword.text().strip(),
        )
        self._load(refresh=False)

    def _open_wizard(self) -> None:
        rows = [row for row in self._rows if not row.position_key]
        if rows:
            _AssignmentWizard(self.service, rows, self._positions, self).exec()
            self._load(refresh=False)

    def _refresh_settings(self) -> None:
        positions = self.service.list_positions(enabled_only=False)
        self._position_table.set_data(
            [
                {
                    "Kürzel": item.initials,
                    "Position": item.label,
                    "Farbe": item.color,
                    "Aktiv": "ja" if item.enabled else "nein",
                    "__key": item.key,
                }
                for item in positions
            ]
        )
        self._rule_table.set_data(
            [
                {
                    "Position": str(getattr(item, "position_key", "")).upper(),
                    "Bezeichnung": str(getattr(item, "label", "")),
                    "Empfänger": str(getattr(item, "payee_normalized", "")),
                    "IBAN": _RuleDialog._masked_iban(str(getattr(item, "counterparty_iban", ""))),
                    "Zweck": str(getattr(item, "purpose_contains", "")),
                    "Aktiv": "ja" if getattr(item, "enabled", False) else "nein",
                    "__id": str(getattr(item, "id", "")),
                    "__enabled": bool(getattr(item, "enabled", False)),
                }
                for item in self.service.list_position_rules()
            ]
        )
        self._supplier_table.set_data(
            [
                {
                    "Bezeichnung": str(getattr(item, "label", "")),
                    "Empfänger": str(getattr(item, "payee_normalized", "")),
                    "IBAN": _RuleDialog._masked_iban(str(getattr(item, "counterparty_iban", ""))),
                    "Website": str(getattr(item, "url", "")),
                    "Aktiv": "ja" if getattr(item, "enabled", False) else "nein",
                    "__id": str(getattr(item, "id", "")),
                    "__enabled": bool(getattr(item, "enabled", False)),
                }
                for item in self.service.list_supplier_links()
            ]
        )

    def _edit_selected_position(self) -> None:
        selected = self._position_table.selected_row_data()
        if not selected:
            return
        position = next(
            (
                item
                for item in self.service.list_positions(enabled_only=False)
                if item.key == selected.get("__key")
            ),
            None,
        )
        self._edit_position(position)

    def _edit_position(self, position: ExpensePositionView | None) -> None:
        dialog = _PositionDialog(position, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.service.save_position(
            key=dialog.key.text().strip().lower(),
            label=dialog.label.text().strip(),
            initials=dialog.initials.text().strip(),
            color=dialog.color.text().strip(),
            enabled=dialog.enabled.isChecked(),
        )
        self._positions = self.service.list_positions()
        self._on_loaded(self._rows)

    def _toggle_selected_rule(self) -> None:
        selected = self._rule_table.selected_row_data()
        if selected and self.service.set_position_rule_enabled(
            str(selected.get("__id") or ""), not bool(selected.get("__enabled"))
        ):
            self._refresh_settings()

    def _add_rule(self) -> None:
        dialog = _StandaloneRuleDialog(self._positions, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.service.add_position_rule(
            position_key=str(dialog.position.currentData()),
            label=dialog.label.text(),
            payee=dialog.payee.text(),
            iban=dialog.iban.text(),
            purpose_contains=dialog.purpose.text(),
        )
        self._refresh_settings()

    def _add_supplier(self) -> None:
        dialog = _SupplierDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.add_supplier_link(
                payee=dialog.payee.text(),
                iban=dialog.iban.text(),
                label=dialog.label.text(),
                url=dialog.url.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Lieferantenportal", str(exc))
            return
        self._refresh_settings()

    def _toggle_selected_supplier(self) -> None:
        selected = self._supplier_table.selected_row_data()
        if selected and self.service.set_supplier_link_enabled(
            str(selected.get("__id") or ""), not bool(selected.get("__enabled"))
        ):
            self._refresh_settings()

    @staticmethod
    def _open_url(url: str) -> None:
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))

    def _on_error(self, exc: Exception) -> None:
        self._status.setText("Abruf fehlgeschlagen")
        QMessageBox.warning(self, "Ausgabenprüfung", str(exc))
