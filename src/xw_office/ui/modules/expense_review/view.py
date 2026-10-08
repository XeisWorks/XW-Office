"""FINANZEN > Ausgabenprüfung."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from PySide6.QtCore import (
    QDate,
    QEvent,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
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
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.worker import BackgroundWorker
from xw_office.services.commission.service import format_euro_amount
from xw_office.services.expenses.reference_parser import format_expense_original_details
from xw_office.services.expenses.service import BankExpenseRow, ExpenseAuditService, ExpensePositionView
from xw_office.services.expenses.xw_flow_expense_client import FlowExpense, XwFlowExpenseClient
from xw_office.services.secrets.service import SecretService
from xw_office.ui.modules.expense_review.manual_expense_dialog import ManualExpenseDialog
from xw_office.ui.widgets.data_table import DataTable

if False:  # pragma: no cover
    from xw_office.core.container import Container


_HEADERS = ["Datum", "Empfänger", "Zweck / Referenz", "Betrag", "Kategorie", "Beleg"]
_ROOT = Path(__file__).resolve().parents[5]
_GERMAN_MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
_CUSTOM_PERIOD = "custom"


def _make_labels_copyable(widget: QWidget) -> None:
    flags = Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
    for label in widget.findChildren(QLabel):
        label.setTextInteractionFlags(flags)


def _show_copyable_message(
    parent: QWidget, title: str, text: str, icon: QMessageBox.Icon = QMessageBox.Icon.Information
) -> None:
    box = QMessageBox(icon, title, text, parent=parent)
    box.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    box.exec()


class _PositionDelegate(QStyledItemDelegate):
    position_clicked = Signal(str, str)

    def paint(self, painter: QPainter, option: Any, index: Any) -> None:
        painter.save()
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
        content_width = len(positions) * diameter + max(0, len(positions) - 1) * gap
        left = cell.left() + max(0, (cell.width() - content_width) // 2)
        top = cell.top() + max(1, (cell.height() - diameter) // 2)
        return [
            (QRect(left + index * (diameter + gap), top, diameter, diameter), position)
            for index, position in enumerate(positions)
        ]


class _DocumentDelegate(QStyledItemDelegate):
    url_clicked = Signal(str)
    supplier_link_requested = Signal(object)
    attachment_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sevdesk = QIcon(str(_ROOT / "icons" / "sevdesk.png"))

    def paint(self, painter: QPainter, option: Any, index: Any) -> None:
        super().paint(painter, option, index)
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        for rect, kind, _url in self._icon_rects(option.rect, row):
            if kind == "sevdesk":
                self._sevdesk.paint(painter, rect)
            elif kind == "website":
                self._paint_globe(painter, rect)
            else:
                self._paint_link_add(painter, rect)

    def editorEvent(self, event: QEvent, model: Any, option: Any, index: Any) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease or not isinstance(event, QMouseEvent):
            return False
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        for rect, kind, url in self._icon_rects(option.rect, row):
            if not rect.contains(event.position().toPoint()):
                continue
            if kind == "add_supplier":
                self.supplier_link_requested.emit(row)
            elif kind == "attachment":
                self.attachment_requested.emit(row)
            elif url.startswith("https://"):
                self.url_clicked.emit(url)
                return True
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
        else:
            result.append((QRect(left, top, 22, 22), "add_supplier", ""))
        for _attachment_id in row.get("__manual_attachment_ids") or []:
            result.append((QRect(left + 27, top, 22, 22), "attachment", ""))
            left += 27
        return result

    @staticmethod
    def _paint_globe(painter: QPainter, rect: QRect) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(rect.adjusted(1, 1, -1, -1))
        painter.setBrush(QColor("#08b7d6"))
        painter.setPen(QPen(QColor("#14d5bf"), 1.5))
        painter.drawEllipse(area)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#062f63"), 1.5))
        painter.drawEllipse(area)
        painter.drawEllipse(
            QRectF(area.left() + area.width() * 0.27, area.top(), area.width() * 0.46, area.height())
        )
        painter.drawLine(
            int(area.left()), int(area.center().y()), int(area.right()), int(area.center().y())
        )
        painter.restore()

    @staticmethod
    def _paint_link_add(painter: QPainter, rect: QRect) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#e5e7eb")
        pen = QPen(color, 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(rect.left() + 4, rect.bottom() - 7, rect.right() - 9, rect.top() + 6)
        painter.drawLine(rect.left() + 8, rect.bottom() - 3, rect.right() - 5, rect.top() + 10)
        badge = QRect(rect.right() - 9, rect.bottom() - 9, 11, 11)
        painter.setBrush(QColor("#111827"))
        painter.setPen(QPen(QColor("#f9fafb"), 1.2))
        painter.drawEllipse(badge)
        painter.setPen(QPen(QColor("#f9fafb"), 1.8))
        painter.drawLine(
            badge.center().x() - 3, badge.center().y(), badge.center().x() + 3, badge.center().y()
        )
        painter.drawLine(
            badge.center().x(), badge.center().y() - 3, badge.center().x(), badge.center().y() + 3
        )
        painter.restore()


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
        layout.addRow("Kategorie", self.position)
        layout.addRow("Empfänger exakt", self.use_payee)
        layout.addRow("IBAN exakt", self.use_iban)
        layout.addRow("Zweck enthält", self.keyword)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        _make_labels_copyable(self)

    @staticmethod
    def _masked_iban(value: str) -> str:
        text = value.replace(" ", "")
        return f"{text[:4]} … {text[-4:]}" if len(text) > 8 else text

    def _accept_if_valid(self) -> None:
        if not (self.use_payee.isChecked() or self.use_iban.isChecked() or self.keyword.text().strip()):
            _show_copyable_message(self, "Zuordnungsregel", "Bitte mindestens ein Kriterium wählen.")
            return
        self.accept()


class _PositionDialog(QDialog):
    def __init__(self, position: ExpensePositionView | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kategorie bearbeiten" if position else "Kategorie anlegen")
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
        _make_labels_copyable(self)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color.text()), self)
        if color.isValid():
            self.color.setText(color.name())


class _SupplierDialog(QDialog):
    def __init__(
        self,
        *,
        label: str = "",
        payee: str = "",
        iban: str = "",
        url: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lieferantenportal bearbeiten" if url else "Lieferantenportal anlegen")
        layout = QFormLayout(self)
        self.label = QLineEdit(label)
        self.payee = QLineEdit(payee)
        self.iban = QLineEdit(iban)
        self.url = QLineEdit(url or "https://")
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
        _make_labels_copyable(self)


class _PurposeRuleDialog(QDialog):
    def __init__(
        self,
        *,
        label: str = "",
        payee: str = "",
        remove_text: str = "",
        sample: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verwendungszweck bereinigen")
        layout = QFormLayout(self)
        self.label = QLineEdit(label)
        self.payee = QLineEdit(payee)
        self.remove_text = QLineEdit(remove_text)
        self.remove_text.setPlaceholderText("Text, der künftig ausgeblendet wird")
        layout.addRow("Bezeichnung", self.label)
        layout.addRow("Empfänger", self.payee)
        layout.addRow("Text entfernen", self.remove_text)
        if sample:
            preview = QLabel(sample)
            preview.setWordWrap(True)
            preview.setStyleSheet("color: #9ca3af;")
            layout.addRow("Aktuelle Anzeige", preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        _make_labels_copyable(self)

    def _accept_if_valid(self) -> None:
        if not self.payee.text().strip() or not self.remove_text.text().strip():
            _show_copyable_message(self, "Zweckbereinigung", "Empfänger und Text sind erforderlich.")
            return
        self.accept()


class _StandaloneRuleDialog(QDialog):
    def __init__(self, positions: list[ExpensePositionView], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kategorienregel anlegen")
        layout = QFormLayout(self)
        self.position = QComboBox()
        for item in positions:
            self.position.addItem(f"{item.initials} · {item.label}", item.key)
        self.label = QLineEdit()
        self.payee = QLineEdit()
        self.iban = QLineEdit()
        self.purpose = QLineEdit()
        layout.addRow("Kategorie", self.position)
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
        _make_labels_copyable(self)

    def _accept_if_valid(self) -> None:
        if not any((self.payee.text().strip(), self.iban.text().strip(), self.purpose.text().strip())):
            _show_copyable_message(self, "Zuordnungsregel", "Bitte mindestens ein Kriterium eingeben.")
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
        _make_labels_copyable(self)
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
        self._manual_worker: BackgroundWorker | None = None
        self._assignment_workers: list[BackgroundWorker] = []
        self._tenant_key = "xw"
        self._tenant_tabs = QTabBar()
        self._tenant_tabs.setObjectName("expenseTenantTabs")
        self._tenant_tabs.setAccessibleName("Mandant für die Ausgabenüberprüfung")
        self._tenant_tabs.setExpanding(True)
        self._tenant_tabs.setDrawBase(False)
        self._tenant_tabs.setMinimumHeight(62)
        self._tenant_tabs.setStyleSheet(
            "QTabBar#expenseTenantTabs {"
            "  background: #101b38; border: 1px solid #36558d; border-radius: 9px; padding: 5px;"
            "}"
            "QTabBar#expenseTenantTabs::tab {"
            "  background: #1b2a4b; border: 1px solid #3e5684; border-radius: 6px;"
            "  color: #cbd7ef; font-size: 15px; font-weight: 700; margin: 1px; padding: 9px 24px;"
            "}"
            "QTabBar#expenseTenantTabs::tab:hover { background: #2a416d; color: #ffffff; }"
            "QTabBar#expenseTenantTabs::tab:selected {"
            "  background: #c6922d; border-color: #f0ca73; color: #111827;"
            "}"
        )
        self._tenant_tabs.addTab("XeisWorks")
        self._tenant_tabs.addTab("WüdaraMusi")
        self._rows: list[BankExpenseRow] = []
        self._all_rows: list[BankExpenseRow] = []
        self._missing_loaded_period: tuple[date, date] | None = None
        self._load_period: tuple[date, date] | None = None
        self._last_load_was_refresh = False
        self._positions: list[ExpensePositionView] = []
        self._settings = QSettings("XeisWorks", "XW Office")
        self._header_save_timer = QTimer(self)
        self._header_save_timer.setSingleShot(True)
        self._header_save_timer.timeout.connect(self._save_table_header)
        self._period = QComboBox()
        self._period_sync = False
        self._start = QDateEdit()
        self._end = QDateEdit()
        self._account_label = QLabel()
        self._status = QLabel("Noch nicht geladen")
        self._wizard_button = QPushButton("Offene Zuordnungen prüfen")
        self._table = DataTable(_HEADERS)
        self._missing_table = DataTable(_HEADERS)
        self._manual_table = DataTable(
            ["Datum", "Empfänger", "Zweck", "Betrag", "USt.", "Zahlungsart", "Kategorie", "Beleg", "Prüfung", "Rückzahlung"]
        )
        self._position_table = DataTable(["Kürzel", "Kategorie", "Farbe", "Aktiv"])
        self._rule_table = DataTable(["Kategorie", "Bezeichnung", "Empfänger", "IBAN", "Zweck", "Aktiv"])
        self._supplier_table = DataTable(["Bezeichnung", "Empfänger", "IBAN", "Website", "Aktiv"])
        self._purpose_rule_table = DataTable(["Bezeichnung", "Empfänger", "Text entfernen", "Aktiv"])
        self._position_delegate = _PositionDelegate(self)
        self._document_delegate = _DocumentDelegate(self)
        self._build_ui()
        QTimer.singleShot(0, lambda: self._load(refresh=False))

    @property
    def service(self) -> ExpenseAuditService:
        service = self._container.resolve(ExpenseAuditService)
        for_tenant = getattr(service, "for_tenant", None)
        return for_tenant(self._tenant_key) if callable(for_tenant) else service

    @property
    def flow_expense_client(self) -> XwFlowExpenseClient:
        return XwFlowExpenseClient(
            self._container.config,
            self._container.resolve(SecretService),
        )

    @property
    def _tenant_label(self) -> str:
        return "WüdaraMusi" if self._tenant_key == "wuedara" else "XeisWorks"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._tenant_tabs.currentChanged.connect(self._on_tenant_changed)
        root.addWidget(self._tenant_tabs)
        controls = QHBoxLayout()
        self._account_label.setText(f"Konto: {self._tenant_label}")
        controls.addWidget(self._account_label)
        self._start.setCalendarPopup(True)
        self._end.setCalendarPopup(True)
        today = datetime.now(tz=ZoneInfo("Europe/Vienna")).date()
        self._setup_period_selector(today)
        controls.addWidget(QLabel("Zeitraum:"))
        controls.addWidget(self._period)
        controls.addWidget(QLabel("Von:"))
        controls.addWidget(self._start)
        controls.addWidget(QLabel("Bis:"))
        controls.addWidget(self._end)
        self._period.currentIndexChanged.connect(self._apply_period_preset)
        self._start.dateChanged.connect(self._mark_custom_period)
        self._end.dateChanged.connect(self._mark_custom_period)
        self._apply_period_preset(self._period.currentIndex())
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
        tabs.currentChanged.connect(self._on_main_tab_changed)
        root.addWidget(tabs, stretch=1)

    def _setup_period_selector(self, today: date) -> None:
        month = today.replace(day=1)
        for _ in range(6):
            self._period.addItem(
                f"{_GERMAN_MONTHS[month.month - 1]} {month.year}",
                (month.year, month.month),
            )
            month = (month - timedelta(days=1)).replace(day=1)
        self._period.addItem("Benutzerdefiniert", _CUSTOM_PERIOD)
        self._period.setCurrentIndex(1)

    def _apply_period_preset(self, index: int) -> None:
        year_month = self._period.itemData(index)
        if not isinstance(year_month, tuple) or len(year_month) != 2:
            return
        year, month = year_month
        if not isinstance(year, int) or not isinstance(month, int):
            return
        start = date(year, month, 1)
        next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        end = next_month - timedelta(days=1)
        self._period_sync = True
        try:
            self._start.setDate(QDate(start.year, start.month, start.day))
            self._end.setDate(QDate(end.year, end.month, end.day))
        finally:
            self._period_sync = False

    def _mark_custom_period(self, _: QDate) -> None:
        if self._period_sync or self._period.currentData() == _CUSTOM_PERIOD:
            return
        self._period.setCurrentIndex(self._period.findData(_CUSTOM_PERIOD))

    def _configure_expense_table(self, table: DataTable) -> None:
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setItemDelegateForColumn(4, self._position_delegate)
        table.setItemDelegateForColumn(5, self._document_delegate)
        if table is self._table:
            state = self._settings.value("expense_review/bank_table_header")
            if state is not None:
                header.restoreState(state)
            header.sectionResized.connect(lambda *_args: self._schedule_table_header_save())
            header.sectionMoved.connect(lambda *_args: self._schedule_table_header_save())

    def _build_bank_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._configure_expense_table(self._table)
        layout.addWidget(self._table, stretch=1)
        manual_header = QHBoxLayout()
        manual_header.addWidget(QLabel("Zusätzliche Ausgaben – bar oder privat bezahlt"))
        manual_header.addStretch()
        add_manual = QPushButton("+")
        add_manual.setToolTip("Neue zusätzliche Ausgabe")
        add_manual.setFixedSize(38, 32)
        add_manual.clicked.connect(self._add_manual_expense)
        manual_header.addWidget(add_manual)
        manual_refresh = QPushButton()
        manual_refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        manual_refresh.setToolTip("Zusätzliche Ausgaben aktualisieren")
        manual_refresh.setFixedSize(38, 32)
        manual_refresh.clicked.connect(self._load_manual_expenses)
        manual_header.addWidget(manual_refresh)
        layout.addLayout(manual_header)
        self._configure_manual_table()
        layout.addWidget(self._manual_table, stretch=1)
        actions = QHBoxLayout()
        purpose_rule = QPushButton("Zweck für Empfänger bereinigen")
        purpose_rule.clicked.connect(self._add_purpose_rule_from_selected)
        actions.addWidget(purpose_rule)
        actions.addStretch()
        layout.addLayout(actions)
        self._position_delegate.position_clicked.connect(self._assign_position)
        self._document_delegate.url_clicked.connect(self._open_url)
        self._document_delegate.supplier_link_requested.connect(self._add_supplier_link_from_row)
        self._document_delegate.attachment_requested.connect(self._open_manual_attachment)
        return page

    def _configure_manual_table(self) -> None:
        header = self._manual_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._manual_table.setItemDelegateForColumn(6, self._position_delegate)
        state = self._settings.value(f"expense_review/{self._tenant_key}/manual_table_header")
        if state is not None:
            header.restoreState(state)
        header.sectionResized.connect(lambda *_args: self._schedule_table_header_save())
        header.sectionMoved.connect(lambda *_args: self._schedule_table_header_save())

    def _build_missing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        header = QHBoxLayout()
        header.addStretch()
        refresh = QPushButton()
        refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        refresh.setIconSize(QSize(26, 26))
        refresh.setFixedSize(38, 38)
        refresh.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        refresh.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: #27324b; border-radius: 6px; }"
        )
        refresh.setToolTip("Fehlende Belege erneut prüfen")
        refresh.clicked.connect(self._refresh_missing_receipts)
        header.addWidget(refresh)
        layout.addLayout(header)
        self._configure_expense_table(self._missing_table)
        layout.addWidget(self._missing_table, stretch=1)
        return page

    def _build_settings_tab(self) -> QWidget:
        tabs = QTabWidget()
        positions = QWidget()
        position_layout = QVBoxLayout(positions)
        position_layout.addWidget(self._position_table)
        position_actions = QHBoxLayout()
        add_position = QPushButton("Kategorie anlegen")
        add_position.clicked.connect(lambda: self._edit_position(None))
        edit_position = QPushButton("Auswahl bearbeiten")
        edit_position.clicked.connect(self._edit_selected_position)
        position_actions.addWidget(add_position)
        position_actions.addWidget(edit_position)
        position_actions.addStretch()
        position_layout.addLayout(position_actions)
        tabs.addTab(positions, "Kategorien")

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
        edit_supplier = QPushButton("Auswahl bearbeiten")
        edit_supplier.clicked.connect(self._edit_selected_supplier)
        supplier_actions.addWidget(add_supplier)
        supplier_actions.addWidget(edit_supplier)
        supplier_actions.addWidget(toggle_supplier)
        supplier_actions.addStretch()
        supplier_layout.addLayout(supplier_actions)
        tabs.addTab(suppliers, "Lieferantenportale")

        purpose_rules = QWidget()
        purpose_layout = QVBoxLayout(purpose_rules)
        purpose_layout.addWidget(self._purpose_rule_table)
        purpose_actions = QHBoxLayout()
        add_purpose = QPushButton("Zweckregel anlegen")
        add_purpose.clicked.connect(self._add_purpose_rule)
        edit_purpose = QPushButton("Auswahl bearbeiten")
        edit_purpose.clicked.connect(self._edit_selected_purpose_rule)
        toggle_purpose = QPushButton("Ausgewählte Regel aktivieren/deaktivieren")
        toggle_purpose.clicked.connect(self._toggle_selected_purpose_rule)
        purpose_actions.addWidget(add_purpose)
        purpose_actions.addWidget(edit_purpose)
        purpose_actions.addWidget(toggle_purpose)
        purpose_actions.addStretch()
        purpose_layout.addLayout(purpose_actions)
        tabs.addTab(purpose_rules, "Verwendungszwecke")
        return tabs

    def _load(
        self,
        *,
        refresh: bool = True,
        force_document_refresh: bool = False,
        retry_unlinked_documents: bool = False,
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._positions = self.service.list_positions()
        self._status.setText("Bankbewegungen werden geladen …")
        start = cast(date, self._start.date().toPython())
        end = cast(date, self._end.date().toPython())
        self._load_period = (start, end)
        self._last_load_was_refresh = refresh
        self._worker = BackgroundWorker(
            lambda: self.service.list_bank_expenses(
                start=start,
                end=end,
                refresh=refresh,
                force_document_refresh=force_document_refresh,
                outgoing_only=False,
                retry_unlinked_documents=retry_unlinked_documents,
            )
        )
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._tenant_tabs.setEnabled(False)
        self._worker.signals.finished.connect(self._on_load_finished)
        self._worker.start()
        self._load_manual_expenses()

    def _load_manual_expenses(self) -> None:
        if not hasattr(self._container, "config"):
            return
        if self._manual_worker is not None and self._manual_worker.isRunning():
            return
        start = cast(date, self._start.date().toPython())
        end = cast(date, self._end.date().toPython())
        client = self.flow_expense_client
        category_snapshot = [position.__dict__ for position in self.service.list_positions(enabled_only=False)]

        def fetch_manual() -> list[FlowExpense]:
            try:
                client.sync_categories(tenant_key=self._tenant_key, positions=category_snapshot)
            except Exception:
                # Category mirroring is additive; a temporary bridge problem must
                # not hide already captured expenses.
                pass
            return client.fetch(tenant_key=self._tenant_key, start=start, end=end, active_only=False)

        self._manual_worker = BackgroundWorker(
            fetch_manual
        )
        self._manual_worker.signals.result.connect(self._on_manual_loaded)
        self._manual_worker.signals.error.connect(self._on_manual_error)
        self._manual_worker.signals.finished.connect(lambda: setattr(self, "_manual_worker", None))
        self._manual_worker.start()

    def _on_manual_error(self, exc: Exception) -> None:
        if hasattr(self._container, "config") and self.flow_expense_client.is_configured():
            self._status.setText(f"Zusätzliche Ausgaben nicht geladen: {exc}")

    def _on_manual_loaded(self, payload: object) -> None:
        values = [item for item in payload if isinstance(item, FlowExpense)] if isinstance(payload, list) else []
        positions = [position.__dict__ for position in self._positions]
        self._manual_table.set_data(
            [
                {
                    "Datum": item.expense_date or "offen",
                    "Empfänger": item.recipient,
                    "Zweck": item.purpose,
                    "Betrag": format_euro_amount(item.gross_amount or Decimal("0")),
                    "USt.": f"{item.tax_rate_bps / 100:g} %" if item.tax_rate_bps is not None else "unbekannt",
                    "Zahlungsart": item.payment_source,
                    "Kategorie": "",
                    "Beleg": "vorhanden" if item.receipt_state == "attached" else "fehlt",
                    "Prüfung": item.accounting_status,
                    "Rückzahlung": item.reimbursement_status,
                    "__transaction_id": f"manual:{item.id}",
                    "__manual_id": item.id,
                    "__manual_version": item.version,
                    "__manual_attachment_ids": list(item.attachment_ids),
                    "__positions": positions,
                    "__position_key": item.category_key,
                    "__align__Betrag": "right",
                    "__align__Kategorie": "center",
                    "__fg__Betrag": "#ff9c9c",
                }
                for item in values
            ]
        )
        self._manual_table.resizeColumnsToContents()

    def _open_manual_attachment(self, row: object) -> None:
        data = row if isinstance(row, dict) else {}
        expense_id = str(data.get("__manual_id") or "")
        attachment_ids = [str(item) for item in data.get("__manual_attachment_ids") or []]
        if not expense_id or not attachment_ids:
            return
        worker = BackgroundWorker(
            lambda: self.flow_expense_client.attachment_view_url(
                expense_id=expense_id, attachment_id=attachment_ids[0]
            )
        )
        worker.signals.result.connect(self._open_url)
        worker.signals.error.connect(self._on_manual_error)
        worker.start()

    def _on_load_finished(self) -> None:
        self._worker = None
        self._tenant_tabs.setEnabled(True)

    def _on_loaded(self, payload: object) -> None:
        self._all_rows = [
            row for row in payload if isinstance(row, BankExpenseRow)
        ] if isinstance(payload, list) else []
        self._rows = [row for row in self._all_rows if row.amount < 0]
        self._populate(self._table, self._rows)
        missing = [row for row in self._all_rows if row.document_link_scan_complete and not row.documents]
        self._populate(self._missing_table, missing, receipt_mode=True)
        incomplete = any(not row.document_link_scan_complete for row in self._all_rows)
        open_count = sum(not row.position_key for row in self._rows)
        suffix = " · Belegscan unvollständig" if incomplete else ""
        self._status.setText(
            f"{len(self._rows)} ausgehende Zahlungen · Konto {self._tenant_label}{suffix}"
        )
        self._wizard_button.setText(f"{open_count} offene Zuordnungen prüfen")
        self._wizard_button.setVisible(open_count > 0)
        self._refresh_settings()

        if self._last_load_was_refresh:
            self._missing_loaded_period = self._load_period

    def _on_main_tab_changed(self, index: int) -> None:
        if index != 1:
            return
        period = (
            cast(date, self._start.date().toPython()),
            cast(date, self._end.date().toPython()),
        )
        if self._missing_loaded_period != period:
            self._refresh_missing_receipts()

    def _on_tenant_changed(self, index: int) -> None:
        tenant_key = "wuedara" if index == 1 else "xw"
        if tenant_key == self._tenant_key:
            return
        self._header_save_timer.stop()
        self._save_table_header()
        self._tenant_key = tenant_key
        self._account_label.setText(f"Konto: {self._tenant_label}")
        state_key = f"expense_review/{self._tenant_key}/bank_table_header"
        state = self._settings.value(state_key)
        if state is not None:
            self._table.horizontalHeader().restoreState(state)
        manual_state = self._settings.value(f"expense_review/{self._tenant_key}/manual_table_header")
        if manual_state is not None:
            self._manual_table.horizontalHeader().restoreState(manual_state)
        self._rows = []
        self._all_rows = []
        self._missing_loaded_period = None
        self._table.set_data([])
        self._missing_table.set_data([])
        self._manual_table.set_data([])
        self._load(refresh=True)

    def _populate(
        self, table: DataTable, rows: list[BankExpenseRow], *, receipt_mode: bool = False
    ) -> None:
        position_payload = [position.__dict__ for position in self._positions]
        table.set_data(
            [
                {
                    "Datum": row.value_date.strftime("%d.%m.%Y"),
                    "Empfänger": row.payee,
                    "Zweck / Referenz": row.purpose,
                    "Betrag": self._amount_text(row, receipt_mode=receipt_mode),
                    "Kategorie": "",
                    "Beleg": self._document_text(row),
                    "__transaction_id": row.transaction_id,
                    "__iban": row.iban,
                    "__payee": row.payee,
                    "__purpose": row.purpose,
                    "__raw_payee": row.raw_payee,
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
                    "__tooltip__Kategorie": self._position_tooltip(row),
                    "__tooltip__Beleg": self._document_tooltip(row),
                    "__align__Betrag": "right",
                    "__align__Kategorie": "center",
                    "__fg__Betrag": self._amount_color(row, receipt_mode=receipt_mode),
                }
                for row in rows
            ]
        )
        table.resizeColumnsToContents()

    @staticmethod
    def _amount_text(row: BankExpenseRow, *, receipt_mode: bool) -> str:
        amount = format_euro_amount(row.amount)
        return f"+{amount}" if receipt_mode and row.amount > 0 else amount

    @staticmethod
    def _amount_color(row: BankExpenseRow, *, receipt_mode: bool) -> str:
        del receipt_mode
        return "#ff9c9c" if row.amount < 0 else "#7ce7a0" if row.amount > 0 else ""

    @staticmethod
    def _document_text(row: BankExpenseRow) -> str:
        if row.documents:
            return "     " * len(row.documents) + ("  " if row.supplier_url else "")
        if row.supplier_url:
            return "      "
        return "nicht geprüft" if not row.document_link_scan_complete else "      "

    @staticmethod
    def _document_tooltip(row: BankExpenseRow) -> str:
        parts = [f"sevDesk: {doc.document_number}" for doc in row.documents]
        if row.supplier_url:
            parts.append("Lieferantenportal öffnen")
        else:
            parts.append("Lieferantenportal-Link anlegen")
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
        if transaction_id.startswith("manual:"):
            self._assign_manual_position(transaction_id.removeprefix("manual:"), position_key)
            return
        self._all_rows = [
            replace(row, position_key=position_key, position_source="manual")
            if row.transaction_id == transaction_id
            else row
            for row in self._all_rows
        ]
        self._rows = [row for row in self._all_rows if row.amount < 0]
        self._populate(self._table, self._rows)
        missing = [
            row for row in self._all_rows if row.document_link_scan_complete and not row.documents
        ]
        self._populate(self._missing_table, missing, receipt_mode=True)
        self._table.clearSelection()
        self._missing_table.clearSelection()
        QTimer.singleShot(0, self._table.clearSelection)
        QTimer.singleShot(0, self._missing_table.clearSelection)

        worker = BackgroundWorker(
            lambda: self.service.assign_transaction_position(
                transaction_id=transaction_id, position_key=position_key
            )
        )
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda: self._assignment_workers.remove(worker))
        self._assignment_workers.append(worker)
        worker.start()

    def _assign_manual_position(self, expense_id: str, position_key: str) -> None:
        selected = next(
            (row for row in self._manual_table.source_rows_data() if row.get("__manual_id") == expense_id),
            None,
        )
        if not selected:
            return
        position = next((item for item in self._positions if item.key == position_key), None)
        if position is None:
            return
        worker = BackgroundWorker(
            lambda: self.flow_expense_client.update_category(
                expense_id=expense_id,
                version=int(selected.get("__manual_version") or 1),
                category_key=position_key,
                category_label=position.label,
            )
        )
        worker.signals.result.connect(lambda _: self._load_manual_expenses())
        worker.signals.error.connect(self._on_manual_error)
        worker.start()

    def _refresh_missing_receipts(self) -> None:
        self._load(refresh=True, retry_unlinked_documents=True)

    def _remember_selected_rule(self) -> None:
        selected = self._table.selected_row_data()
        if not selected:
            _show_copyable_message(self, "Ausgabenprüfung", "Bitte zuerst eine Zahlung auswählen.")
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
                    "Kategorie": item.label,
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
                    "Kategorie": str(getattr(item, "position_key", "")).upper(),
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
        self._purpose_rule_table.set_data(
            [
                {
                    "Bezeichnung": str(getattr(item, "label", "")),
                    "Empfänger": str(getattr(item, "payee_normalized", "")),
                    "Text entfernen": str(getattr(item, "remove_text", "")),
                    "Aktiv": "ja" if getattr(item, "enabled", False) else "nein",
                    "__id": str(getattr(item, "id", "")),
                    "__enabled": bool(getattr(item, "enabled", False)),
                }
                for item in self.service.list_purpose_rules()
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
        dialog = _SupplierDialog(parent=self)
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
            _show_copyable_message(self, "Lieferantenportal", str(exc), QMessageBox.Icon.Warning)
            return
        self._refresh_settings()

    def _add_supplier_link_from_row(self, row: object) -> None:
        data = row if isinstance(row, dict) else {}
        payee = str(data.get("__raw_payee") or data.get("__payee") or "")
        dialog = _SupplierDialog(label=str(data.get("__payee") or payee), payee=payee, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.add_supplier_link(
                payee=dialog.payee.text(),
                iban=str(data.get("__iban") or ""),
                label=dialog.label.text(),
                url=dialog.url.text(),
            )
        except ValueError as exc:
            _show_copyable_message(self, "Lieferantenportal", str(exc), QMessageBox.Icon.Warning)
            return
        self._load(refresh=False)

    def _edit_selected_supplier(self) -> None:
        selected = self._supplier_table.selected_row_data()
        if not selected:
            return
        supplier = next(
            (item for item in self.service.list_supplier_links() if str(item.id) == selected.get("__id")),
            None,
        )
        if supplier is None:
            return
        dialog = _SupplierDialog(
            label=supplier.label,
            payee=supplier.payee_normalized,
            iban=supplier.counterparty_iban,
            url=supplier.url,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update_supplier_link(
                link_id=str(supplier.id),
                payee=dialog.payee.text(),
                iban=dialog.iban.text(),
                label=dialog.label.text(),
                url=dialog.url.text(),
            )
        except ValueError as exc:
            _show_copyable_message(self, "Lieferantenportal", str(exc), QMessageBox.Icon.Warning)
            return
        self._load(refresh=False)

    def _toggle_selected_supplier(self) -> None:
        selected = self._supplier_table.selected_row_data()
        if selected and self.service.set_supplier_link_enabled(
            str(selected.get("__id") or ""), not bool(selected.get("__enabled"))
        ):
            self._refresh_settings()

    def _add_purpose_rule_from_selected(self) -> None:
        selected = self._table.selected_row_data()
        if not selected:
            _show_copyable_message(self, "Zweckbereinigung", "Bitte zuerst eine Zahlung auswählen.")
            return
        payee = str(selected.get("__raw_payee") or selected.get("__payee") or "")
        dialog = _PurposeRuleDialog(
            label=payee,
            payee=payee,
            sample=str(selected.get("__purpose") or ""),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.add_purpose_rule(
                payee=dialog.payee.text(),
                remove_text=dialog.remove_text.text(),
                label=dialog.label.text(),
            )
        except ValueError as exc:
            _show_copyable_message(self, "Zweckbereinigung", str(exc), QMessageBox.Icon.Warning)
            return
        self._load(refresh=False)

    def _add_purpose_rule(self) -> None:
        dialog = _PurposeRuleDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.add_purpose_rule(
                payee=dialog.payee.text(),
                remove_text=dialog.remove_text.text(),
                label=dialog.label.text(),
            )
        except ValueError as exc:
            _show_copyable_message(self, "Zweckbereinigung", str(exc), QMessageBox.Icon.Warning)
            return
        self._refresh_settings()

    def _edit_selected_purpose_rule(self) -> None:
        selected = self._purpose_rule_table.selected_row_data()
        if not selected:
            return
        rule = next(
            (item for item in self.service.list_purpose_rules() if str(item.id) == selected.get("__id")),
            None,
        )
        if rule is None:
            return
        dialog = _PurposeRuleDialog(
            label=rule.label,
            payee=rule.payee_normalized,
            remove_text=rule.remove_text,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update_purpose_rule(
                rule_id=str(rule.id),
                payee=dialog.payee.text(),
                remove_text=dialog.remove_text.text(),
                label=dialog.label.text(),
            )
        except ValueError as exc:
            _show_copyable_message(self, "Zweckbereinigung", str(exc), QMessageBox.Icon.Warning)
            return
        self._load(refresh=False)

    def _toggle_selected_purpose_rule(self) -> None:
        selected = self._purpose_rule_table.selected_row_data()
        if selected and self.service.set_purpose_rule_enabled(
            str(selected.get("__id") or ""), not bool(selected.get("__enabled"))
        ):
            self._refresh_settings()

    def _schedule_table_header_save(self) -> None:
        self._header_save_timer.start(350)

    def _save_table_header(self) -> None:
        self._settings.setValue(
            f"expense_review/{self._tenant_key}/bank_table_header",
            self._table.horizontalHeader().saveState(),
        )
        self._settings.setValue(
            f"expense_review/{self._tenant_key}/manual_table_header",
            self._manual_table.horizontalHeader().saveState(),
        )
        self._settings.sync()

    def _add_manual_expense(self) -> None:
        if not hasattr(self._container, "config"):
            _show_copyable_message(self, "Zusätzliche Ausgabe", "XW-Flow Ausgaben-Bridge ist in diesem Testcontainer nicht verfügbar.", QMessageBox.Icon.Warning)
            return
        if not self.flow_expense_client.is_configured():
            _show_copyable_message(self, "Zusätzliche Ausgabe", "XW-Flow Ausgaben-Bridge ist nicht konfiguriert.", QMessageBox.Icon.Warning)
            return
        dialog = ManualExpenseDialog(self.flow_expense_client, self._tenant_key, self._positions, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_manual_expenses()

    def closeEvent(self, event: Any) -> None:
        self._save_table_header()
        super().closeEvent(event)

    @staticmethod
    def _open_url(url: str) -> None:
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))

    def _on_error(self, exc: Exception) -> None:
        self._status.setText("Abruf fehlgeschlagen")
        _show_copyable_message(self, "Ausgabenprüfung", str(exc), QMessageBox.Icon.Warning)
