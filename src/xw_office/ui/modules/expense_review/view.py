"""FINANZEN > Ausgabenprüfung."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import httpx
from PySide6.QtCore import (
    QDate,
    QEvent,
    QModelIndex,
    QRect,
    QRectF,
    QSignalBlocker,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QMouseEvent, QPainter, QPen, QShowEvent, QTransform,
)
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
    QStyleOptionFrame,
    QStyledItemDelegate,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from xw_office.core.worker import BackgroundWorker
from xw_office.services.commission.service import format_euro_amount
from xw_office.services.expenses.reference_parser import format_expense_original_details
from xw_office.services.expenses.service import (
    BankExpenseLoad,
    BankExpenseRow,
    ExpenseAuditService,
    ExpensePositionView,
    WUEDARA_EXPENSE_POSITION,
)
from xw_office.services.expenses.xw_flow_expense_client import FlowExpense, XwFlowExpenseClient
from xw_office.services.secrets.service import SecretService
from xw_office.ui.modules.expense_review.additional_expenses import (
    ADDITIONAL_EXPENSE_HEADERS,
    manual_expense_rows,
    shared_bank_expense_rows,
)
from xw_office.ui.modules.expense_review.manual_expense_dialog import ManualExpenseDialog
from xw_office.ui.widgets.data_table import DataTable

if TYPE_CHECKING:
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
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ReviewLoad:
    bank: BankExpenseLoad
    positions: list[ExpensePositionView]
    shared_bank: list[BankExpenseRow] = field(default_factory=list)


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
        elif not row.get("__manual_id") and not row.get("__read_only"):
            result.append((QRect(left, top, 22, 22), "add_supplier", ""))
        if row.get("__manual_attachment_ids"):
            result.append((QRect(left, top, 22, 22), "attachment", ""))
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
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
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
        self._sample = sample
        for line_edit in (self.label, self.payee, self.remove_text):
            line_edit.setCursorPosition(0)
            line_edit.textChanged.connect(self._fit_fields_to_contents)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_fields_to_contents()

    def _fit_fields_to_contents(self) -> None:
        layout = cast(QFormLayout, self.layout())
        margins = layout.contentsMargins()
        label_width = max(
            (
                widget.sizeHint().width()
                for line_edit in (self.label, self.payee, self.remove_text)
                if (widget := layout.labelForField(line_edit)) is not None
            ),
            default=0,
        )
        spacing = max(
            layout.horizontalSpacing(),
            self.style().pixelMetric(QStyle.PixelMetric.PM_LayoutHorizontalSpacing),
        )
        max_dialog_width = self.screen().availableGeometry().width() - 80
        overhead = margins.left() + margins.right() + label_width + spacing
        required_width = 0
        for line_edit in (self.label, self.payee, self.remove_text):
            metrics = line_edit.fontMetrics()
            text_width = max(
                metrics.horizontalAdvance(line_edit.text() or line_edit.placeholderText()),
                metrics.horizontalAdvance(self._sample),
            )
            option = QStyleOptionFrame()
            line_edit.initStyleOption(option)
            width = line_edit.style().sizeFromContents(
                QStyle.ContentsType.CT_LineEdit, option,
                QSize(text_width + 24, metrics.height()), line_edit,
            ).width()
            required_width = max(required_width, width)
        field_width = min(required_width, max(1, max_dialog_width - overhead))
        for line_edit in (self.label, self.payee, self.remove_text):
            line_edit.setMinimumWidth(field_width)
        self.resize(
            min(max(self.width(), self.sizeHint().width()), max_dialog_width),
            self.sizeHint().height(),
        )

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


class ExpenseReviewView(QWidget):
    """Review outgoing XeisWorks transactions with configurable positions."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._workers: dict[str, BackgroundWorker] = {}
        self._manual_workers: dict[str, BackgroundWorker] = {}
        self._assignment_workers: list[BackgroundWorker] = []
        self._tenant_loads: dict[
            str, tuple[list[BankExpenseRow], list[ExpensePositionView], tuple[date, date]]
        ] = {}
        self._tenant_period_states: dict[str, tuple[date, date]] = {}
        self._document_refresh_tenants: set[str] = set()
        self._missing_refresh_button: QPushButton | None = None
        self._missing_refresh_icon = QIcon()
        self._missing_refresh_angle = 0
        self._missing_refresh_timer = QTimer(self)
        self._missing_refresh_timer.setInterval(90)
        self._missing_refresh_timer.timeout.connect(self._advance_missing_refresh_icon)
        self._period_reload_timer = QTimer(self)
        self._period_reload_timer.setSingleShot(True)
        self._period_reload_timer.setInterval(250)
        self._period_reload_timer.timeout.connect(self._load_cached_then_sync)
        self._cache_poll_timer = QTimer(self)
        self._cache_poll_timer.setInterval(60_000)
        self._cache_poll_timer.timeout.connect(self._poll_cache)
        self._cache_poll_timer.start()
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
        self._positions: list[ExpensePositionView] = []
        self._manual_expenses: list[FlowExpense] = []
        self._shared_bank_expenses: list[BankExpenseRow] = []
        self._source_reload_pending = False
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
        self._sync_status = QLabel()
        self._sync_status.setWordWrap(True)
        self._category_filter = QComboBox()
        self._category_label = QLabel("Kategorie:")
        self._category_filter.addItem("Alle Kategorien", None)
        self._category_filter.addItem("Ohne Kategorie", "")
        self._missing_only = QCheckBox("Nur fehlende Belege anzeigen")
        self._unassigned_only = QCheckBox("Nur offene Zuordnungen anzeigen")
        self._table = DataTable(_HEADERS)
        self._manual_table = DataTable(ADDITIONAL_EXPENSE_HEADERS)
        self._manual_heading = QLabel("Zusätzliche Ausgaben – bar oder privat bezahlt")
        self._position_table = DataTable(["Kürzel", "Kategorie", "Farbe", "Aktiv"])
        self._rule_table = DataTable(["Kategorie", "Bezeichnung", "Empfänger", "IBAN", "Zweck", "Aktiv"])
        self._supplier_table = DataTable(["Bezeichnung", "Empfänger", "IBAN", "Website", "Aktiv"])
        self._purpose_rule_table = DataTable(["Bezeichnung", "Empfänger", "Text entfernen", "Aktiv"])
        self._position_delegate = _PositionDelegate(self)
        self._document_delegate = _DocumentDelegate(self)
        self._build_ui()
        self._start.dateChanged.connect(self._queue_period_reload)
        self._end.dateChanged.connect(self._queue_period_reload)
        QTimer.singleShot(0, self._load_cached_then_sync)

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
        controls.addStretch()
        root.addLayout(controls)
        root.addWidget(self._sync_status)
        root.addWidget(self._build_bank_tab(), stretch=1)
        self._settings_dialog = QDialog(self)
        self._settings_dialog.resize(1000, 650)
        settings_layout = QVBoxLayout(self._settings_dialog)
        settings_layout.addWidget(self._build_settings_tab())
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self._settings_dialog.reject)
        settings_layout.addWidget(close)
        self._apply_tenant_controls()

    def _setup_period_selector(self, today: date) -> None:
        self._period.clear()
        if self._tenant_key == "wuedara":
            year = today.year
            quarter = (today.month - 1) // 3 + 1
            for _ in range(3):
                self._period.addItem(f"Quartal {quarter} / {year}", ("quarter", year, quarter))
                if quarter == 1:
                    year -= 1
                    quarter = 4
                else:
                    quarter -= 1
            self._period.addItem("Benutzerdefiniert", _CUSTOM_PERIOD)
            self._period.setCurrentIndex(1)
            return
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
        period = self._period_range(self._period.itemData(index))
        if period is None:
            return
        start, end = period
        self._period_sync = True
        try:
            self._start.setDate(QDate(start.year, start.month, start.day))
            self._end.setDate(QDate(end.year, end.month, end.day))
        finally:
            self._period_sync = False
        self._queue_period_reload()

    @staticmethod
    def _period_range(value: object) -> tuple[date, date] | None:
        if not isinstance(value, tuple):
            return None
        if len(value) == 2:
            year, month = value
            if not isinstance(year, int) or not isinstance(month, int):
                return None
            start = date(year, month, 1)
            next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            return start, next_month - timedelta(days=1)
        if len(value) == 3 and value[0] == "quarter":
            _, year, quarter = value
            if not isinstance(year, int) or not isinstance(quarter, int) or not 1 <= quarter <= 4:
                return None
            start = date(year, (quarter - 1) * 3 + 1, 1)
            next_quarter = date(year + 1, 1, 1) if quarter == 4 else date(year, quarter * 3 + 1, 1)
            return start, next_quarter - timedelta(days=1)
        return None

    def _save_period_state(self) -> None:
        self._tenant_period_states[self._tenant_key] = self._selected_period()

    def _selected_period(self) -> tuple[date, date]:
        return (
            cast(date, self._start.date().toPython()),
            cast(date, self._end.date().toPython()),
        )

    def _restore_period_state(self) -> None:
        saved = self._tenant_period_states.get(self._tenant_key)
        self._period_sync = True
        try:
            with QSignalBlocker(self._period):
                self._setup_period_selector(datetime.now(tz=ZoneInfo("Europe/Vienna")).date())
                if saved is None:
                    saved = self._period_range(self._period.currentData())
                if saved is None:
                    return
                matching_index = next(
                    (
                        index
                        for index in range(self._period.count())
                        if self._period_range(self._period.itemData(index)) == saved
                    ),
                    self._period.findData(_CUSTOM_PERIOD),
                )
                self._period.setCurrentIndex(matching_index)
            self._start.setDate(QDate(saved[0].year, saved[0].month, saved[0].day))
            self._end.setDate(QDate(saved[1].year, saved[1].month, saved[1].day))
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
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _build_bank_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._category_label)
        self._category_filter.setAccessibleName("Kontobewegungen nach Kategorie filtern")
        self._category_filter.currentIndexChanged.connect(self._apply_bank_filters)
        toolbar.addWidget(self._category_filter)
        self._missing_only.setToolTip(
            "Nur geprüfte Kontobewegungen mit Lieferantenportal, aber ohne sevDesk-Beleg."
        )
        self._missing_only.toggled.connect(self._apply_bank_filters)
        toolbar.addWidget(self._missing_only)
        self._unassigned_only.toggled.connect(self._apply_bank_filters)
        toolbar.addWidget(self._unassigned_only)
        toolbar.addSpacing(12)
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        self._add_button = QPushButton()
        self._add_button.setIcon(QIcon(str(_ROOT / "icons" / "expense_add.svg")))
        self._add_button.setToolTip("Neue zusätzliche Ausgabe")
        self._add_button.clicked.connect(self._add_manual_expense)
        self._missing_refresh_button = QPushButton()
        self._missing_refresh_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self._missing_refresh_button.setIcon(self._missing_refresh_icon)
        self._missing_refresh_button.setToolTip(
            "Kontobewegungen, neue/geänderte sevDesk-Belege und zusätzliche Ausgaben aktualisieren"
        )
        self._missing_refresh_button.clicked.connect(self._refresh_receipts_and_manual_expenses)
        self._settings_button = QPushButton()
        self._settings_button.setIcon(QIcon(str(_ROOT / "icons" / "expense_settings.svg")))
        self._settings_button.setToolTip("Einstellungen zur Ausgabenprüfung")
        self._settings_button.clicked.connect(self._open_settings)
        for button in (self._add_button, self._missing_refresh_button, self._settings_button):
            button.setIconSize(QSize(32, 32))
            button.setFixedSize(46, 46)
            button.setAccessibleName(button.toolTip())
            button.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 0px; }"
                "QPushButton:hover, QPushButton:focus { background: #27324b; border-radius: 6px; }"
                "QPushButton:disabled { background: transparent; }"
            )
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self._configure_expense_table(self._table)
        self._table.doubleClicked.connect(self._on_bank_double_clicked)
        layout.addWidget(self._table, stretch=1)
        manual_header = QHBoxLayout()
        manual_header.addWidget(self._manual_heading)
        manual_header.addStretch()
        layout.addLayout(manual_header)
        self._configure_manual_table()
        layout.addWidget(self._manual_table)
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
        self._manual_table.setItemDelegateForColumn(7, self._document_delegate)
        state = self._settings.value(f"expense_review/{self._tenant_key}/manual_table_header")
        if state is not None:
            header.restoreState(state)
        self._manual_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        header.sectionResized.connect(lambda *_args: self._schedule_table_header_save())
        header.sectionMoved.connect(lambda *_args: self._schedule_table_header_save())
        header.geometriesChanged.connect(self._resize_manual_table)
        self._manual_table.horizontalScrollBar().rangeChanged.connect(self._resize_manual_table)
        self._resize_manual_table()

    def _resize_manual_table(self) -> None:
        table = self._manual_table
        scrollbar = table.horizontalScrollBar()
        scroll_height = scrollbar.sizeHint().height() if scrollbar.maximum() > 0 else 0
        table.setFixedHeight(
            table.horizontalHeader().height()
            + 2 * table.verticalHeader().defaultSectionSize()
            + 2 * table.frameWidth()
            + scroll_height
        )

    def _on_bank_double_clicked(self, index: QModelIndex) -> None:
        if index.column() == 2:
            self._table.selectRow(index.row())
            self._add_purpose_rule_from_selected()

    def _open_settings(self) -> None:
        self._settings_dialog.setWindowTitle(f"Ausgabenprüfung – {self._tenant_label} – Einstellungen")
        self._refresh_settings()
        self._settings_dialog.exec()

    def _refresh_receipts_and_manual_expenses(self) -> None:
        self._refresh_missing_receipts()
        self._load_manual_expenses()

    def _build_settings_tab(self) -> QWidget:
        tabs = QTabWidget()
        self._settings_tabs = tabs
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
        load_manual_expenses: bool = True,
        sync_after: bool = False,
        automatic: bool = False,
    ) -> None:
        tenant_key = self._tenant_key
        existing_worker = self._workers.get(tenant_key)
        if existing_worker is not None:
            return
        service = self.service
        self._sync_status.setText(
            "Gespeicherter Stand bleibt sichtbar · Aktualisierung im Hintergrund …"
            if refresh else "Gespeicherte Kontobewegungen werden geladen …"
        )
        start = cast(date, self._start.date().toPython())
        end = cast(date, self._end.date().toPython())
        period = (start, end)
        if refresh:
            self._document_refresh_tenants.add(tenant_key)
            self._sync_missing_refresh_indicator()

        def load_data() -> _ReviewLoad:
            if refresh:
                bank = service.synchronize_bank_expenses(start=start, end=end, force=not automatic)
            else:
                rows = service.list_bank_expenses(
                    start=start, end=end, refresh=False, outgoing_only=False
                )
                bank = BankExpenseLoad(
                    rows, document_scan_complete=all(row.document_link_scan_complete for row in rows)
                )
            shared_bank = (
                service.list_wuedara_shared_bank_expenses(start=start, end=end)
                if tenant_key == "wuedara" else []
            )
            positions = service.list_positions(enabled_only=False) if tenant_key == "xw" else []
            return _ReviewLoad(bank, positions, shared_bank)

        succeeded = False

        def loaded(payload: object) -> None:
            nonlocal succeeded
            if not isValid(self):
                return
            if not isinstance(payload, _ReviewLoad):
                self._on_load_error(tenant_key, TypeError("Ungültiges Ergebnis der Ausgabenprüfung."))
                return
            self._on_loaded(tenant_key, payload, period, refresh=refresh)
            succeeded = True

        worker = BackgroundWorker(load_data)
        self._workers[tenant_key] = worker
        worker.signals.result.connect(loaded)
        worker.signals.error.connect(
            lambda exc: self._on_load_error(tenant_key, exc)
            if isValid(self) and (
                tenant_key != self._tenant_key or period == self._selected_period()
            )
            else None
        )
        worker.signals.finished.connect(
            lambda: self._on_load_finished(
                tenant_key, worker, period, sync_after=sync_after and succeeded
            )
        )
        worker.start()
        if load_manual_expenses:
            self._load_manual_expenses()

    def _load_cached_then_sync(self) -> None:
        if not isValid(self):
            return
        self._period_reload_timer.stop()
        if self._start.date() > self._end.date():
            self._sync_status.setText("Bitte einen gültigen Zeitraum wählen: Von darf nicht nach Bis liegen.")
            return
        cached = self._tenant_loads.get(self._tenant_key)
        if cached is not None and cached[2] != self._selected_period():
            self._manual_expenses = []
            self._shared_bank_expenses = []
            self._manual_table.set_data([])
        self._load(refresh=False, sync_after=True)

    def _queue_period_reload(self) -> None:
        if not self._period_sync:
            self._period_reload_timer.start()

    def _poll_cache(self) -> None:
        if self.isVisible() and self._tenant_key not in self._workers:
            self._load_cached_then_sync()

    def _load_manual_expenses(self) -> None:
        if not hasattr(self._container, "config"):
            return
        tenant_key = self._tenant_key
        existing_worker = self._manual_workers.get(tenant_key)
        if existing_worker is not None:
            return
        start = cast(date, self._start.date().toPython())
        end = cast(date, self._end.date().toPython())
        period = (start, end)
        client = self.flow_expense_client
        service = self.service

        def fetch_manual() -> list[FlowExpense]:
            positions = (
                service.list_positions(enabled_only=False) if tenant_key == "xw"
                else [WUEDARA_EXPENSE_POSITION]
            )
            category_snapshot = [position.__dict__ for position in positions]
            try:
                client.sync_categories(tenant_key=tenant_key, positions=category_snapshot)
            except httpx.HTTPError as exc:
                # Category mirroring is additive; a temporary bridge problem must
                # not hide already captured expenses.
                logger.warning("Ausgabenkategorien für %s nicht synchronisiert: %s", tenant_key, exc)
            return client.fetch_for_review(tenant_key=tenant_key, start=start, end=end)

        worker = BackgroundWorker(fetch_manual)
        self._manual_workers[tenant_key] = worker
        worker.signals.result.connect(
            lambda payload: self._on_manual_loaded(tenant_key, payload)
            if isValid(self) and period == self._selected_period() else None
        )
        worker.signals.error.connect(
            lambda exc: self._on_manual_error(tenant_key, exc)
            if isValid(self) and period == self._selected_period() else None
        )
        worker.signals.finished.connect(
            lambda: self._on_manual_load_finished(tenant_key, worker, period)
        )
        worker.start()

    def _on_manual_load_finished(
        self, tenant_key: str, worker: BackgroundWorker, period: tuple[date, date]
    ) -> None:
        if self._manual_workers.get(tenant_key) is not worker:
            return
        self._manual_workers.pop(tenant_key)
        if isValid(self) and tenant_key == self._tenant_key and period != self._selected_period():
            self._load_manual_expenses()
        self._reload_shared_sources_if_ready()

    def _on_manual_error(self, tenant_key: str, exc: Exception) -> None:
        if isValid(self) and tenant_key == self._tenant_key:
            self._sync_status.setText(f"Zusätzliche Ausgaben nicht geladen: {exc}")

    def _on_manual_loaded(self, tenant_key: str, payload: object) -> None:
        if not isValid(self) or tenant_key != self._tenant_key:
            return
        self._manual_expenses = (
            [item for item in payload if isinstance(item, FlowExpense)]
            if isinstance(payload, list) else []
        )
        self._render_additional_expenses()

    def _render_additional_expenses(self) -> None:
        rows = manual_expense_rows(
            self._manual_expenses, self._positions, tenant_key=self._tenant_key
        )
        if self._tenant_key == "wuedara":
            rows.extend(shared_bank_expense_rows(self._shared_bank_expenses))
        self._manual_table.set_data(rows)
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
        worker.signals.error.connect(self._on_error)
        worker.start()

    def _on_load_finished(
        self,
        tenant_key: str,
        worker: BackgroundWorker,
        period: tuple[date, date],
        *,
        sync_after: bool,
    ) -> None:
        if self._workers.get(tenant_key) is not worker:
            return
        self._workers.pop(tenant_key)
        self._document_refresh_tenants.discard(tenant_key)
        if not isValid(self):
            return
        if tenant_key == self._tenant_key:
            self._sync_missing_refresh_indicator()
            if period != self._selected_period():
                self._load_cached_then_sync()
            elif sync_after:
                self._load(refresh=True, automatic=True, load_manual_expenses=False)
        self._reload_shared_sources_if_ready()

    def _on_load_error(self, tenant_key: str, exc: Exception) -> None:
        if isValid(self) and tenant_key == self._tenant_key:
            self._sync_status.setText(f"Aktualisierung fehlgeschlagen · Gespeicherter Stand bleibt sichtbar: {exc}")

    def _on_loaded(
        self,
        tenant_key: str,
        payload: _ReviewLoad,
        period: tuple[date, date],
        *,
        refresh: bool,
    ) -> None:
        all_rows = payload.bank.rows
        positions = payload.positions
        self._tenant_loads[tenant_key] = (all_rows, positions, period)
        if tenant_key != self._tenant_key or self._selected_period() != period:
            return
        self._shared_bank_expenses = payload.shared_bank
        self._apply_tenant_load(all_rows, positions)
        if not refresh:
            self._sync_status.setText("Gespeicherter Stand")
        elif not payload.bank.document_scan_complete:
            self._sync_status.setText("Belegscan unvollständig · Vorhandene Belegverknüpfungen bleiben erhalten.")
        elif payload.bank.synced_at is not None:
            local_time = payload.bank.synced_at.astimezone(ZoneInfo("Europe/Vienna"))
            self._sync_status.setText(f"Gemeinsamer Cache · Stand {local_time:%d.%m.%Y %H:%M}")
        else:
            self._sync_status.setText("Kontobewegungen und Belegverknüpfungen aktualisiert")

    def _apply_tenant_load(
        self, all_rows: list[BankExpenseRow], positions: list[ExpensePositionView]
    ) -> None:
        self._positions = [position for position in positions if position.enabled]
        self._all_rows = all_rows
        self._rows = [row for row in all_rows if row.amount < 0]
        self._status.setText(f"{len(self._rows)} ausgehende Zahlungen")
        self._status.setToolTip(f"Konto {self._tenant_label}")
        self._refresh_category_filter(positions)
        self._render_additional_expenses()

    def _apply_bank_filters(self) -> None:
        categories_enabled = self._tenant_key == "xw"
        category = self._category_filter.currentData() if categories_enabled else None
        missing_only = self._missing_only.isChecked()
        rows = self._all_rows if missing_only else self._rows
        filtered = [
            row for row in rows
            if (category is None or row.position_key == category)
            and (
                not categories_enabled or not self._unassigned_only.isChecked()
                or not row.position_key
            )
            and (
                not missing_only
                or (row.supplier_url and row.document_link_scan_complete and not row.documents)
            )
        ]
        self._populate(self._table, filtered, receipt_mode=missing_only)

    def _on_tenant_changed(self, index: int) -> None:
        tenant_key = "wuedara" if index == 1 else "xw"
        if tenant_key == self._tenant_key:
            return
        self._save_period_state()
        self._header_save_timer.stop()
        self._save_table_header()
        self._tenant_key = tenant_key
        self._source_reload_pending = False
        self._account_label.setText(f"Konto: {self._tenant_label}")
        self._restore_period_state()
        self._period_reload_timer.stop()
        state_key = f"expense_review/{self._tenant_key}/bank_table_header"
        state = self._settings.value(state_key)
        if state is not None:
            self._table.horizontalHeader().restoreState(state)
        manual_state = self._settings.value(f"expense_review/{self._tenant_key}/manual_table_header")
        if manual_state is not None:
            self._manual_table.horizontalHeader().restoreState(manual_state)
        for table in (self._table, self._manual_table):
            table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._apply_tenant_controls()
        self._manual_expenses = []
        self._shared_bank_expenses = []
        cached = self._tenant_loads.get(tenant_key)
        has_cached_period = cached is not None and cached[2] == self._selected_period()
        if cached is not None and has_cached_period:
            self._apply_tenant_load(cached[0], cached[1])
        else:
            self._rows = []
            self._all_rows = []
            self._table.set_data([])
            self._status.setText("Noch nicht geladen")
        self._manual_table.set_data([])
        self._sync_missing_refresh_indicator()
        worker = self._workers.get(tenant_key)
        if worker is None:
            self._load_cached_then_sync()
        else:
            self._sync_status.setText(f"Konto {self._tenant_label} wird geladen …")
        self._load_manual_expenses()

    def _apply_tenant_controls(self) -> None:
        categories_enabled = self._tenant_key == "xw"
        self._category_label.setVisible(categories_enabled)
        self._category_filter.setVisible(categories_enabled)
        self._unassigned_only.setVisible(categories_enabled)
        self._table.setColumnHidden(4, not categories_enabled)
        self._manual_table.setColumnHidden(6, not categories_enabled)
        self._settings_tabs.setTabVisible(0, categories_enabled)
        self._settings_tabs.setTabVisible(1, categories_enabled)
        if not categories_enabled and self._settings_tabs.currentIndex() < 2:
            self._settings_tabs.setCurrentIndex(2)
        self._manual_heading.setText(
            "Zusätzliche Ausgaben – bar, privat oder über XeisWorks bezahlt"
            if not categories_enabled else "Zusätzliche Ausgaben – bar oder privat bezahlt"
        )

    def _populate(
        self, table: DataTable, rows: list[BankExpenseRow], *, receipt_mode: bool = False
    ) -> None:
        position_payload = [position.__dict__ for position in self._positions]
        table.set_data(
            [
                {
                    "Datum": row.value_date.strftime("%d.%m.%Y"),
                    "__sort__Datum": row.value_date.isoformat(),
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
                    ) + "\nDoppelklick: Verwendungszweck für diesen Empfänger bereinigen",
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
        if self._tenant_key != "xw":
            _show_copyable_message(
                self, "Kategorie", "Kategorien werden nur im Bereich XeisWorks zugeordnet."
            )
            return
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
        self._tenant_loads[self._tenant_key] = (
            self._all_rows,
            self._positions,
            self._selected_period(),
        )
        self._apply_bank_filters()
        self._table.clearSelection()
        QTimer.singleShot(0, self._table.clearSelection)

        service = self.service
        worker = BackgroundWorker(
            lambda: service.assign_transaction_position(
                transaction_id=transaction_id, position_key=position_key
            )
        )
        worker.signals.error.connect(self._on_error)
        worker.signals.result.connect(lambda _: self._on_assignment_saved(manual=False))
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
        client = self.flow_expense_client
        worker = BackgroundWorker(
            lambda: client.update_category(
                expense_id=expense_id,
                version=int(selected.get("__manual_version") or 1),
                category_key=position_key,
                category_label=position.label,
            )
        )
        worker.signals.result.connect(lambda _: self._on_assignment_saved(manual=True))
        worker.signals.error.connect(lambda exc: self._on_manual_error("xw", exc))
        worker.signals.finished.connect(lambda: self._assignment_workers.remove(worker))
        self._assignment_workers.append(worker)
        worker.start()

    def _on_assignment_saved(self, *, manual: bool) -> None:
        if not isValid(self):
            return
        if self._tenant_key == "wuedara":
            self._source_reload_pending = True
            self._reload_shared_sources_if_ready()
        elif manual:
            self._load_manual_expenses()

    def _reload_shared_sources_if_ready(self) -> None:
        if (
            isValid(self) and self._tenant_key == "wuedara" and self._source_reload_pending
            and self._tenant_key not in self._workers
            and self._tenant_key not in self._manual_workers
        ):
            self._source_reload_pending = False
            self._load_cached_then_sync()

    def _refresh_missing_receipts(self) -> None:
        worker = self._workers.get(self._tenant_key)
        if worker is not None:
            return
        self._load(refresh=True, load_manual_expenses=False)

    def _sync_missing_refresh_indicator(self) -> None:
        self._set_missing_refresh_pending(self._tenant_key in self._document_refresh_tenants)

    def _set_missing_refresh_pending(self, pending: bool) -> None:
        if self._missing_refresh_button is None:
            return
        self._missing_refresh_button.setEnabled(not pending)
        if pending:
            self._missing_refresh_angle = 0
            self._missing_refresh_timer.start()
            return
        self._missing_refresh_timer.stop()
        self._missing_refresh_button.setIcon(self._missing_refresh_icon)

    def _advance_missing_refresh_icon(self) -> None:
        if self._missing_refresh_button is None:
            return
        self._missing_refresh_angle = (self._missing_refresh_angle + 45) % 360
        pixmap = self._missing_refresh_icon.pixmap(QSize(32, 32))
        if pixmap.isNull():
            return
        self._missing_refresh_button.setIcon(
            QIcon(pixmap.transformed(QTransform().rotate(self._missing_refresh_angle)))
        )

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

    def _refresh_category_filter(self, positions: list[ExpensePositionView]) -> None:
        if self._tenant_key != "xw":
            self._apply_bank_filters()
            return
        category = self._category_filter.currentData()
        with QSignalBlocker(self._category_filter):
            self._category_filter.clear()
            self._category_filter.addItem("Alle Kategorien", None)
            self._category_filter.addItem("Ohne Kategorie", "")
            for position in positions:
                self._category_filter.addItem(
                    f"{position.initials} · {position.label}", position.key
                )
            self._category_filter.setCurrentIndex(
                max(0, self._category_filter.findData(category))
            )
        self._apply_bank_filters()

    def _refresh_settings(self) -> None:
        positions = (
            self.service.list_positions(enabled_only=False) if self._tenant_key == "xw" else []
        )
        self._refresh_category_filter(positions)
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
                for item in (
                    self.service.list_position_rules() if self._tenant_key == "xw" else []
                )
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
        self._tenant_loads[self._tenant_key] = (
            self._all_rows,
            self._positions,
            self._selected_period(),
        )
        self._apply_tenant_load(self._all_rows, self._positions)

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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._tenant_key in self._tenant_loads and self._tenant_key not in self._workers:
            QTimer.singleShot(0, self._load_cached_then_sync)

    @staticmethod
    def _open_url(url: str) -> None:
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))

    def _on_error(self, exc: Exception) -> None:
        self._sync_status.setText("Abruf fehlgeschlagen")
        _show_copyable_message(self, "Ausgabenprüfung", str(exc), QMessageBox.Icon.Warning)
