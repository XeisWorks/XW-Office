"""Rechnungen module — invoice list from sevDesk."""
from __future__ import annotations

from datetime import datetime
import html
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRect, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QDesktopServices,
    QFont,
    QHideEvent,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QStyledItemDelegate,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.core.worker import BackgroundWorker
from xw_office.services.background_jobs.service import BackgroundJobManager, CancelToken, JobHandle
from xw_office.services.daily_business.service import DailyBusinessService
from xw_office.services.draft_invoice.service import (
    DraftInvoiceService,
    ProductIssueDecision,
    ProductPreflightApplyResult,
    ProductPreflightPlan,
)
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.digital_licenses import DigitalLicenseService
from xw_office.services.inventory import InventoryService
from xw_office.services.plc.label_archive import PlcLabelArchive
from xw_office.services.printer_status.service import PrinterStatusService
from xw_office.services.products.catalog import Product, ProductCatalogService, normalize_legacy_title
from xw_office.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_office.services.secrets.service import SecretService
from xw_office.services.sendungen.service import OffeneSendungenService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.ui.modules.rechnungen.offene_ueberweisungen_dialog import OffeneUeberweisungenDialog
from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.services.wix.client import WixOrdersClient
from xw_office.ui.modules.rechnungen.digital_licenses_dialog import DigitalLicensesDialog
from xw_office.ui.modules.rechnungen.offene_sendungen_dialog import OffeneSendungenDialog
from xw_office.ui.modules.rechnungen.special_order_dialog import SpecialOrderDialog
from xw_office.ui.modules.rechnungen.open_invoice_overview import (
    OpenInvoiceOverview,
    PrintProductAggregate,
    overview_from_visible_summaries,
    overview_payload_from_object,
    resolve_open_invoice_overview,
)
from xw_office.ui.modules.rechnungen.plc_label_dialog import PlcLabelPrintDialog
from xw_office.ui.modules.rechnungen.plc_statistics_dialog import PlcStatisticsDialog
from xw_office.services.plc.statistics import PlcStatisticsService
from xw_office.ui.modules.rechnungen.product_preflight_dialog import ProductPreflightDialog
from xw_office.ui.modules.rechnungen.refund_dialog import RefundDialog
from xw_office.ui.widgets.data_table import DataTable
from xw_office.ui.widgets.progress_overlay import ProgressOverlay
from xw_office.ui.widgets.search_bar import SearchBar
from xw_office.ui.widgets.toolbar import Toolbar

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_TABLE_COLUMNS = [
    "sevDesk",
    "WIX",
    "Datum",
    "🔎",
    "BETRAG",
    "Kunde",
    "Hinweise",
    "AKTIONEN",
    "FULFILLMENT",
    "ID",
]

_PAGE_SIZE = 10
_DRAFT_STATUS = 100
_OPEN_STATUS: int | None = None
_DRAFT_INITIAL_LOAD_LIMIT = 50
_OPEN_AUTO_LOAD_LIMIT = 50
# Contexts are immutable enough for one application session.  The persistent
# Wix snapshot cache is retained for 180 days; dropping the UI representation
# after 75 seconds only caused needless conversion work when users revisited a
# row in the same list.
_WIX_CONTEXT_CACHE_TTL_SECONDS = 6 * 60 * 60
_WIX_WARM_BATCH_SIZE = 3
_WIX_WARM_QUEUE_LIMIT = 8
_SIDE_JOB_QUEUE = "rechnungen-side"
_PRIORITY_OPEN_OVERVIEW = 10
_PRIORITY_HINT_PREFETCH = 20
_PRIORITY_WIX_WARMUP = 30


class _HintsIconDelegate(QStyledItemDelegate):
    """Paint invoice hint icons in a compact row-friendly style."""

    _ICON_FILES = {
        "print": "print.png",
        "note": "",
        "alternateshippingaddress": "alternateshippingaddress.png",
        "country": "country.png",
        "plc": "plc.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._tinted_cache: dict[str, QPixmap] = {}
        self._icons_dir = Path(__file__).resolve().parents[5] / "icons"

    def _icon_for_key(self, key: str) -> QPixmap | None:
        if key in self._cache:
            pix = self._cache[key]
            return pix if not pix.isNull() else None
        file_name = self._ICON_FILES.get(key)
        if not file_name:
            self._cache[key] = QPixmap()
            return None
        pix = QPixmap(str(self._icons_dir / file_name))
        self._cache[key] = pix
        return pix if not pix.isNull() else None

    def _tinted_icon_for_key(self, key: str, size: int) -> QPixmap | None:
        cache_key = f"{key}:{size}"
        if cache_key in self._tinted_cache:
            pix = self._tinted_cache[cache_key]
            return pix if not pix.isNull() else None
        source = self._icon_for_key(key)
        if source is None:
            self._tinted_cache[cache_key] = QPixmap()
            return None
        scaled = source.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image = QImage(scaled.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        icon_painter = QPainter(image)
        icon_painter.drawPixmap(0, 0, scaled)
        icon_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        icon_painter.fillRect(image.rect(), QColor("white"))
        icon_painter.end()
        tinted = QPixmap.fromImage(image)
        self._tinted_cache[cache_key] = tinted
        return tinted if not tinted.isNull() else None

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return
        icon_keys = row_data.get("__icons__Hinweise")
        if not isinstance(icon_keys, list) or not icon_keys:
            super().paint(painter, option, index)
            return

        painter.save()
        size = min(18, max(14, option.rect.height() - 6))
        gap = 6
        total_width = len(icon_keys) * size + max(0, len(icon_keys) - 1) * gap
        x = option.rect.x() + max(4, (option.rect.width() - total_width) // 2)
        y = option.rect.y() + max(2, (option.rect.height() - size) // 2)

        for key in icon_keys:
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(x)
            target.setY(y)
            target.setWidth(size)
            target.setHeight(size)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f59e0b"))
            painter.drawEllipse(target)
            painter.restore()
            if str(key) == "note":
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                font = QFont(painter.font())
                font.setBold(True)
                font.setPixelSize(max(9, size - 7))
                painter.setFont(font)
                painter.setPen(QColor("white"))
                painter.drawText(target, Qt.AlignmentFlag.AlignCenter, "N")
                painter.restore()
                x += size + gap
                continue
            icon_size = max(8, size - 7)
            pix = self._tinted_icon_for_key(str(key), icon_size)
            if pix is None:
                x += size + gap
                continue
            icon_x = x + (size - pix.width()) // 2
            icon_y = y + (size - pix.height()) // 2
            painter.drawPixmap(icon_x, icon_y, pix)
            x += size + gap
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _InvoiceStatusDelegate(QStyledItemDelegate):
    """Paint consistent round invoice status indicators."""

    _DEFAULT_COLOR = "#94a3b8"

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return

        column = index.model().headerData(
            index.column(),
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.DisplayRole,
        )
        color = str(row_data.get(f"__status_color__{column}") or self._DEFAULT_COLOR).strip()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(
            option.rect,
            option.palette.highlight() if selected else option.palette.base(),
        )
        size = min(16, max(12, option.rect.height() - 8))
        x = option.rect.x() + (option.rect.width() - size) // 2
        y = option.rect.y() + (option.rect.height() - size) // 2
        target = option.rect.adjusted(0, 0, 0, 0)
        target.setX(x)
        target.setY(y)
        target.setWidth(size)
        target.setHeight(size)
        painter.setPen(QColor("#0f172a"))
        painter.setBrush(QColor(color or self._DEFAULT_COLOR))
        painter.drawEllipse(target)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _SevdeskDraftActionDelegate(QStyledItemDelegate):
    """Render a red remove button for drafts without invoice number."""

    @staticmethod
    def _button_geometry(width: int, height: int) -> tuple[int, int, int]:
        size = min(18, max(14, height - 6))
        x = max(4, (width - size) // 2)
        y = max(2, (height - size) // 2)
        return x, y, size

    @classmethod
    def hit_remove_action(cls, *, local_x: float, local_y: float, width: int, height: int) -> bool:
        x, y, size = cls._button_geometry(width, height)
        return x <= int(local_x) <= x + size and y <= int(local_y) <= y + size

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict) or not bool(row_data.get("__draft_remove_enabled__")):
            super().paint(painter, option, index)
            return

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.fillRect(
            option.rect,
            option.palette.highlight() if selected else option.palette.base(),
        )
        x, y, size = self._button_geometry(option.rect.width(), option.rect.height())
        target = option.rect.adjusted(0, 0, 0, 0)
        target.setX(option.rect.x() + x)
        target.setY(option.rect.y() + y)
        target.setWidth(size)
        target.setHeight(size)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dc2626"))
        painter.drawEllipse(target)
        painter.setPen(QColor("white"))
        painter.drawLine(target.left() + 4, target.top() + 4, target.right() - 4, target.bottom() - 4)
        painter.drawLine(target.left() + 4, target.bottom() - 4, target.right() - 4, target.top() + 4)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _ActionsDelegate(QStyledItemDelegate):
    """Paint action icons (Post/PLC + Wix + customer mail) in one column."""

    _ACTION_KEYS = ("post", "wix", "mail")
    _ICON_FILES = {
        "post": "post.png",
        "wix": "wix.png",
        "mail": "mail_sent.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons_dir = Path(__file__).resolve().parents[5] / "icons"
        self._cache: dict[str, QPixmap] = {}

    def _icon_for_key(self, key: str) -> QPixmap | None:
        if key in self._cache:
            pix = self._cache[key]
            return pix if not pix.isNull() else None
        file_name = self._ICON_FILES.get(key)
        if not file_name:
            self._cache[key] = QPixmap()
            return None
        pix = QPixmap(str(self._icons_dir / file_name))
        self._cache[key] = pix
        return pix if not pix.isNull() else None

    @staticmethod
    def _layout(width: int, height: int) -> list[tuple[str, int, int]]:
        size = min(18, max(14, height - 6))
        gap = 6
        total_width = len(_ActionsDelegate._ACTION_KEYS) * size + max(0, len(_ActionsDelegate._ACTION_KEYS) - 1) * gap
        x = max(4, (width - total_width) // 2)
        out: list[tuple[str, int, int]] = []
        for key in _ActionsDelegate._ACTION_KEYS:
            out.append((key, x, size))
            x += size + gap
        return out

    @staticmethod
    def action_at_x(local_x: float, width: int, height: int) -> str:
        for key, x, size in _ActionsDelegate._layout(width, height):
            if x <= int(local_x) <= x + size:
                return key
        return ""

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        y = option.rect.y() + max(2, (option.rect.height() - min(18, max(14, option.rect.height() - 6))) // 2)
        for key, x_local, size in self._layout(option.rect.width(), option.rect.height()):
            pix = self._icon_for_key(key)
            if pix is None:
                continue
            painter.setOpacity(1.0)
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(option.rect.x() + x_local)
            target.setY(y)
            target.setWidth(size)
            target.setHeight(size)
            painter.drawPixmap(target, pix)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _FulfillmentDelegate(QStyledItemDelegate):
    """Paint clickable status chips for fulfillment steps in one column."""

    _CHIPS = (
        ("label_printed", "labelprint.png"),
        ("invoice_printed", "invoice_print.png"),
        ("product_ready", "print.png"),
        ("mail_sent", "mail_sent.png"),
        ("wix_fulfilled", "wix.png"),
        ("payment_booked", "payment.png"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons_dir = Path(__file__).resolve().parents[5] / "icons"
        self._cache: dict[str, QPixmap] = {}

    def _icon(self, file_name: str) -> QPixmap | None:
        if file_name in self._cache:
            pix = self._cache[file_name]
            return pix if not pix.isNull() else None
        pix = QPixmap(str(self._icons_dir / file_name))
        self._cache[file_name] = pix
        return pix if not pix.isNull() else None

    @classmethod
    def _layout(cls, width: int, height: int) -> list[tuple[str, str, int, int]]:
        size = min(18, max(14, height - 6))
        gap = 4
        total = len(cls._CHIPS) * size + max(0, len(cls._CHIPS) - 1) * gap
        x = max(4, (width - total) // 2)
        out: list[tuple[str, str, int, int]] = []
        for key, label in cls._CHIPS:
            out.append((key, label, x, size))
            x += size + gap
        return out

    @classmethod
    def chip_at_x(cls, local_x: float, width: int, height: int) -> str:
        for key, _file, x, size in cls._layout(width, height):
            if key == "payment_booked":
                continue
            if x <= int(local_x) <= x + size:
                return key
        return ""

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return
        payload = row_data.get("__fulfillment__")
        if not isinstance(payload, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        has_run = bool(payload.get("last_run_iso"))
        for key, file_name, x_local, size in self._layout(option.rect.width(), option.rect.height()):
            state = payload.get(key)
            if key == "payment_booked" and not bool(payload.get("payment_applicable")):
                opacity = 0.2
                bg = "#e2e8f0"
            elif not has_run:
                opacity = 0.45
                bg = "#e2e8f0"
            elif bool(state):
                opacity = 1.0
                bg = "#dcfce7"
            else:
                opacity = 1.0
                bg = "#fee2e2"
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(option.rect.x() + x_local)
            target.setY(option.rect.y() + max(2, (option.rect.height() - size) // 2))
            target.setWidth(size)
            target.setHeight(size)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(target, 6, 6)
            pix = self._icon(file_name)
            if pix is not None:
                painter.setOpacity(opacity)
                painter.drawPixmap(target, pix)
                painter.setOpacity(1.0)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _DraftInvoiceDialog(QDialog):
    """Collect Wix order number for draft invoice creation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rechnungs-Entwurf erstellen")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self._preview_ok = False

        layout = QVBoxLayout(self)
        info = QLabel(
            "Wix-Order-Nr eingeben (keine ID).\n"
            "Es wird daraus ein sevDesk-Rechnungsentwurf erzeugt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._order_number = QLineEdit(self)
        self._order_number.setPlaceholderText("z.B. 10023")
        self._order_number.setClearButtonEnabled(True)
        layout.addWidget(self._order_number)

        self._btn_preview = QPushButton("Vorschau laden")
        self._btn_preview.setToolTip("Wix-Order laden und Positionen/Mappings prüfen")
        layout.addWidget(self._btn_preview)

        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(190)
        self._preview.setPlainText("Noch keine Vorschau geladen.")
        layout.addWidget(self._preview)

        self._open_in_sevdesk = QCheckBox("Nach Erstellung in sevDesk öffnen", self)
        self._open_in_sevdesk.setChecked(True)
        layout.addWidget(self._open_in_sevdesk)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #64748b;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def wix_order_number(self) -> str:
        return self._order_number.text().strip()

    @property
    def open_in_sevdesk(self) -> bool:
        return self._open_in_sevdesk.isChecked()

    @property
    def preview_ok(self) -> bool:
        return self._preview_ok

    def on_preview_requested(self, callback: Any) -> None:
        self._btn_preview.clicked.connect(callback)

    def set_preview_result(self, text: str, *, ok: bool) -> None:
        self._btn_preview.setEnabled(True)
        self._btn_preview.setText("Vorschau laden")
        self._preview.setPlainText(text)
        self._preview_ok = ok
        if ok:
            self._status.setText("Vorschau OK: Entwurf kann erstellt werden.")
            self._status.setStyleSheet("color: #15803d;")
        else:
            self._status.setText("Vorschau enthält Probleme. Entwurf wird blockiert.")
            self._status.setStyleSheet("color: #b91c1c;")

    def set_preview_loading(self) -> None:
        """Show immediate feedback while Wix data is loaded."""
        self._preview_ok = False
        self._btn_preview.setEnabled(False)
        self._btn_preview.setText("Vorschau wird geladen...")
        self._preview.setPlainText("Wix-Order und Produktzuordnungen werden geladen...")
        self._status.setText("Bitte warten...")
        self._status.setStyleSheet("color: #64748b;")

    def _accept_if_valid(self) -> None:
        value = self.wix_order_number
        if not value:
            self._status.setText("Bitte eine Wix-Order-Nr eingeben.")
            self._order_number.setFocus()
            return
        if not self._preview_ok:
            self._status.setText("Bitte zuerst eine gültige Vorschau laden.")
            self._status.setStyleSheet("color: #b91c1c;")
            return
        self.accept()


class _CustomLabelDialog(QDialog):
    def __init__(self, container: Container, initial_lines: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self.setWindowTitle("CUSTOM-LABEL")
        self.setModal(True)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        info = QLabel("Lieferadresse zeilenweise eingeben und direkt auf dem Labeldrucker ausgeben.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._editor = QPlainTextEdit(self)
        self._editor.setPlaceholderText("Name\nStrasse Hausnummer\nPLZ Ort\nLand")
        self._editor.setPlainText("\n".join(line for line in (initial_lines or []) if str(line).strip()))
        layout.addWidget(self._editor, stretch=1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #64748b;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        self._btn_print = QPushButton("PRINT")
        buttons.addButton(self._btn_print, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self._btn_print.clicked.connect(self._on_print_clicked)
        layout.addWidget(buttons)

    def _on_print_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        lines = [str(line).strip() for line in self._editor.toPlainText().splitlines() if str(line).strip()]
        if len(lines) < 2:
            QMessageBox.information(
                self,
                "CUSTOM-LABEL",
                "Bitte eine Lieferadresse mit mindestens zwei Zeilen eingeben.",
            )
            return
        self._btn_print.setEnabled(False)
        self._status.setText("Etikett wird gedruckt...")

        def job() -> None:
            from xw_office.services.printing.label_printer import LabelPrinter
            from xw_office.services.printing.print_queue import PrintQueueService

            LabelPrinter(
                self._container.config.printing,
                print_queue=self._container.resolve(PrintQueueService),
            ).print_address(lines)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_print_result)
        self._worker.signals.error.connect(self._on_print_error)
        self._worker.signals.finished.connect(self._on_print_finished)
        self._worker.start()

    def _on_print_result(self, _payload: object) -> None:
        self.accept()

    def _on_print_error(self, exc: Exception) -> None:
        self._status.setText("")
        QMessageBox.warning(self, "CUSTOM-LABEL", f"Label konnte nicht gedruckt werden:\n\n{exc}")

    def _on_print_finished(self) -> None:
        self._worker = None
        self._btn_print.setEnabled(True)


class _PieceListModel(QAbstractListModel):
    """List model for Wix order product details in the invoice panel."""

    BLOCK_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    FLAGGED_ROLE = int(Qt.ItemDataRole.UserRole) + 2
    QUANTITY_ROLE = int(Qt.ItemDataRole.UserRole) + 3
    DETAILS_ROLE = int(Qt.ItemDataRole.UserRole) + 4
    STOCK_ROLE = int(Qt.ItemDataRole.UserRole) + 5
    STOCK_COLOR_ROLE = int(Qt.ItemDataRole.UserRole) + 6
    PRINT_ENABLED_ROLE = int(Qt.ItemDataRole.UserRole) + 7

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, object]] = []

    def set_pieces(self, rows: list[dict[str, object]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        block = row.get("block")
        if not isinstance(block, PieceBlock):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row.get("header") or "")
        if role == self.BLOCK_ROLE:
            return block
        if role == self.FLAGGED_ROLE:
            return bool(row.get("flagged"))
        if role == self.QUANTITY_ROLE:
            return int(row.get("quantity") or 1)
        if role == self.DETAILS_ROLE:
            return list(row.get("details") or [])
        if role == self.STOCK_ROLE:
            return str(row.get("stock") or "")
        if role == self.STOCK_COLOR_ROLE:
            return str(row.get("stock_color") or "#64748b")
        if role == self.PRINT_ENABLED_ROLE:
            return bool(row.get("print_enabled"))
        return None

    def rows(self) -> list[tuple[PieceBlock, int, bool]]:
        result: list[tuple[PieceBlock, int, bool]] = []
        for row in self._rows:
            block = row.get("block")
            if isinstance(block, PieceBlock):
                result.append((block, int(row.get("quantity") or 1), bool(row.get("flagged"))))
        return result

    def set_print_enabled(self, enabled: bool) -> None:
        if not self._rows:
            return
        for row in self._rows:
            row["print_enabled"] = bool(enabled)
        self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 0), [self.PRINT_ENABLED_ROLE])

    def adjust_quantity(self, source_row: int, delta: int) -> None:
        if not (0 <= source_row < len(self._rows)):
            return
        row = self._rows[source_row]
        row["quantity"] = max(1, min(999, max(1, int(row.get("quantity") or 1)) + int(delta)))
        idx = self.index(source_row, 0)
        self.dataChanged.emit(idx, idx, [self.QUANTITY_ROLE])

    def quantity_for_block(self, block: PieceBlock) -> int:
        for row in self._rows:
            if row.get("block") is block:
                return max(1, int(row.get("quantity") or 1))
        return 1


class _PieceDelegate(QStyledItemDelegate):
    """Paint product detail rows and handle lightweight row actions."""

    print_clicked = Signal(object, int)
    manage_clicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        icons_dir = Path(__file__).resolve().parents[5] / "icons"
        self._print_icon = QIcon(str(icons_dir / "print.png"))
        self._manage_icon = QIcon(str(icons_dir / "printondemand.png"))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QColor("#60a5fa") if selected else QColor("#334155"))
        painter.setBrush(QColor("#26364a") if selected else QColor("#1e293b"))
        painter.drawRoundedRect(rect, 6, 6)

        flagged = bool(index.data(_PieceListModel.FLAGGED_ROLE))
        enabled = bool(index.data(_PieceListModel.PRINT_ENABLED_ROLE))
        quantity = int(index.data(_PieceListModel.QUANTITY_ROLE) or 1)
        details = index.data(_PieceListModel.DETAILS_ROLE)
        detail_lines = [str(line) for line in details] if isinstance(details, list) else []
        stock = str(index.data(_PieceListModel.STOCK_ROLE) or "")
        stock_color = QColor(str(index.data(_PieceListModel.STOCK_COLOR_ROLE) or "#64748b"))
        block = index.data(_PieceListModel.BLOCK_ROLE)
        has_print_config = isinstance(block, PieceBlock) and block.has_direct_print_config
        if not isinstance(block, PieceBlock):
            painter.restore()
            return

        qty_rect = QRect(rect.left() + 8, rect.top() + 8, 32, 22)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(qty_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{quantity}x")

        action_width = 40 if flagged else 0
        sku_width = 76
        text_left = qty_rect.right() + 4
        text_width = max(80, rect.right() - text_left - sku_width - action_width - 14)
        title_rect = QRect(text_left, rect.top() + 7, text_width, 22)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(block.name or block.sku or "Unbenanntes Produkt"),
        )

        font.setBold(False)
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)
        description = " | ".join(line for line in detail_lines if line)
        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(
            QRect(text_left, title_rect.bottom() + 2, text_width, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            description,
        )
        painter.setPen(stock_color)
        painter.drawText(
            QRect(text_left, title_rect.bottom() + 20, text_width, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            stock,
        )

        sku_right = rect.right() - action_width - 8
        painter.setPen(QColor("#93c5fd"))
        painter.drawText(
            QRect(sku_right - sku_width, rect.top() + 8, sku_width, 24),
            Qt.AlignmentFlag.AlignCenter,
            str(block.sku or "-"),
        )

        if flagged:
            key = "print" if has_print_config else "manage"
            button_rect = self._button_rects(option.rect, has_print_config=has_print_config)[key]
            active = enabled if key == "print" else True
            painter.setBrush(QColor("#334155") if active else QColor("#1f2937"))
            painter.setPen(QColor("#64748b") if active else QColor("#334155"))
            painter.drawRoundedRect(button_rect, 4, 4)
            icon = self._print_icon if key == "print" else self._manage_icon
            pixmap = icon.pixmap(18, 18)
            if not pixmap.isNull():
                painter.setOpacity(1.0 if active else 0.45)
                painter.drawPixmap(
                    button_rect.center().x() - pixmap.width() // 2,
                    button_rect.center().y() - pixmap.height() // 2,
                    pixmap,
                )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), 82)

    def editorEvent(self, event, model, option, index) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Type.MouseButtonRelease or not index.isValid():
            return super().editorEvent(event, model, option, index)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        block = index.data(_PieceListModel.BLOCK_ROLE)
        if not isinstance(block, PieceBlock):
            return False
        rects = self._button_rects(option.rect, has_print_config=block.has_direct_print_config)
        enabled = bool(index.data(_PieceListModel.PRINT_ENABLED_ROLE))
        if "print" in rects and rects["print"].contains(pos) and enabled:
            qty = int(index.data(_PieceListModel.QUANTITY_ROLE) or 1)
            self.print_clicked.emit(block, qty)
            return True
        if "manage" in rects and rects["manage"].contains(pos):
            self.manage_clicked.emit(block)
            return True
        return super().editorEvent(event, model, option, index)

    @staticmethod
    def _button_rects(row_rect: QRect, *, has_print_config: bool) -> dict[str, QRect]:
        top = row_rect.top() + 26
        right = row_rect.right() - 10
        height = 28
        action = "print" if has_print_config else "manage"
        return {action: QRect(right - 31, top, 32, height)}


class RechnungenView(QWidget):
    """Load and display sevDesk invoices (non-blocking)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._background_jobs = container.resolve(BackgroundJobManager)
        self._worker: BackgroundWorker | None = None
        self._search_worker: BackgroundWorker | None = None
        self._refund_worker: BackgroundWorker | None = None
        self._draft_worker: BackgroundWorker | None = None
        self._draft_product_worker: BackgroundWorker | None = None
        self._draft_preview_worker: BackgroundWorker | None = None
        self._mollie_badge_worker: BackgroundWorker | None = None
        self._stuecke_worker: BackgroundWorker | None = None
        self._wix_meta_worker: BackgroundWorker | None = None
        self._wix_context_worker: BackgroundWorker | None = None
        self._invoice_detail_worker: BackgroundWorker | None = None
        self._customer_mail_worker: BackgroundWorker | None = None
        self._wix_warm_worker: BackgroundWorker | None = None
        self._wix_context_handle: JobHandle | None = None
        self._wix_warm_handle: JobHandle | None = None
        self._hint_worker: BackgroundWorker | None = None
        self._fulfillment_step_worker: BackgroundWorker | None = None
        self._invoice_mail_worker: BackgroundWorker | None = None
        self._delete_draft_worker: BackgroundWorker | None = None
        self._open_overview_worker: BackgroundWorker | None = None
        self._product_print_worker: BackgroundWorker | None = None
        self._did_initial_load = False
        self._print_allowed = False
        self._open_draft_after_create = False
        self._pending_draft_order_number = ""
        self._mollie_alert_count = 0
        self._sendungen_alert_count = 0
        self._digital_licenses_alert_count = 0
        self._search_index: list[dict[str, str]] = []
        self._loaded_rows: list[dict[str, Any]] = []
        self._loaded_summaries: list[InvoiceSummary] = []
        self._loaded_has_more = False
        self._active_load_status: int | None = _DRAFT_STATUS
        self._draft_offset = 0
        self._open_offset = 0
        self._draft_has_more = False
        self._open_has_more = False
        self._open_loaded = False
        self._pending_auto_open_load = False
        self._load_started_at = 0.0
        self._wix_warm_started_at = 0.0
        self._invoice_detail_started_at = 0.0
        self._selected_wix_started_at = 0.0
        self._search_active = False
        self._search_seq = 0
        self._wix_digital_cache: dict[str, bool] = {}
        self._pending_wix_reference = ""
        self._pending_stuecke_reference = ""
        self._wix_context_cache: dict[str, dict[str, object]] = {}
        self._shipping_address_overrides: dict[str, list[str]] = {}
        self._shipping_source_lines: list[str] = []
        self._wix_context_seq = 0
        self._wix_warm_queue: list[str] = []
        self._wix_warm_inflight_refs: set[str] = set()
        self._shutting_down = False
        self._open_overview_seq = 0
        self._pending_open_overview_rows: list[InvoiceSummary] = []
        self._hint_seq = 0
        self._hint_draft_queue: list[str] = []
        self._hint_rest_queue: list[str] = []
        self._hint_inflight_ref = ""
        self._badge_refresh_managed_externally = False
        self._mollie_timer = QTimer(self)
        self._mollie_timer.setInterval(120000)
        self._mollie_timer.timeout.connect(self._refresh_mollie_alert_count)
        self._last_plc_invoice = "—"
        self._next_offset = 0
        self._summaries: list[InvoiceSummary] = []
        self._current_piece_blocks: list[PieceBlock] = []
        self._piece_print_buttons: list[QPushButton | QToolButton] = []
        self._piece_quantity_inputs: list[QSpinBox] = []
        self._piece_quantity_controls: list[tuple[PieceBlock, QSpinBox]] = []
        self._piece_model = _PieceListModel(self)
        self._piece_delegate = _PieceDelegate(self)
        self._piece_delegate.print_clicked.connect(self._on_product_print_clicked)
        self._piece_delegate.manage_clicked.connect(self._on_product_manage_clicked)
        self._append_mode = False
        self._queued_wix_context_ref = ""
        self._queued_invoice_detail_id = ""
        self._detail_context_seq = 0
        self._table_layout_initialized = False
        self._open_overview_key = ""
        self._open_overview_cached_physical = 0
        self._open_overview_cached_digital = 0
        self._open_overview_cached_note = 0
        self._open_overview_cached_plc = 0
        self._open_overview_complete = False
        self._open_overview_products_text = ""
        self._open_overview_products: list[PrintProductAggregate] = []
        self._session_print_products: list[PrintProductAggregate] = []
        self._print_products_last_run = False
        self._last_print_all_products_key: tuple[tuple[str, str, str, int], ...] | None = None
        self._plc_label_archive = PlcLabelArchive()
        self._selected_plc_label_path = ""
        self._plc_archive_lookup_cache: dict[tuple[str, str], str] = {}
        self._printer_status_initialized = False
        self._post_load_prefetch_seq = 0
        self._deferred_load_payload: tuple[
            list[dict[str, Any]],
            list[InvoiceSummary],
            bool,
            int | None,
            bool,
        ] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._toolbar = Toolbar()
        refresh = self._toolbar.add_button(
            "refresh",
            "Aktualisieren",
            tooltip="Erste Seite neu laden",
        )
        refresh.clicked.connect(self._reload_first_page)
        self._btn_draft = self._toolbar.add_button(
            "draft",
            "Rechnungs-Entwurf",
            tooltip="Neuen sevDesk-Rechnungsentwurf aus Wix-Order-Nr erstellen",
        )
        self._btn_draft.clicked.connect(self._on_create_draft_clicked)
        self._btn_custom_label = self._toolbar.add_button(
            "label",
            "CUSTOM-LABEL",
            tooltip="Freie Lieferadresse eingeben und direkt als Label drucken",
        )
        self._btn_custom_label.clicked.connect(self._on_custom_label_clicked)
        self._btn_manual_plc_label = self._toolbar.add_button(
            "manual_plc_label",
            "PLC-LABEL",
            tooltip="PLC-Label mit manuell eingegebener Empfängeradresse erstellen",
        )
        self._btn_manual_plc_label.clicked.connect(self._on_manual_plc_label_clicked)
        self._btn_plc_statistics = self._toolbar.add_button(
            "plc_statistics",
            "PLC-ÜBERSICHT",
            tooltip="Wochen-, Monats- und Jahresstatistik der gedruckten PLC-Labels",
        )
        self._btn_plc_statistics.clicked.connect(self._on_plc_statistics_clicked)
        self._btn_special_order = self._toolbar.add_button(
            "special_order",
            "Sonderauftrag",
            tooltip="Wix Payment Link fuer Sonderauftrag erstellen",
        )
        self._btn_special_order.clicked.connect(self._on_special_order_clicked)
        self._toolbar.add_stretch()
        self._btn_sendungen_alert = self._toolbar.add_button(
            "sendungen_alert",
            "✉ OFFENE SENDUNGEN",
            tooltip="Offene Versand-Mails anzeigen",
        )
        self._btn_sendungen_alert.setStyleSheet(
            "QPushButton {"
            "background-color: #b91c1c; color: white; border-radius: 6px;"
            "font-weight: bold; padding: 0 14px;"
            "}"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self._btn_sendungen_alert.clicked.connect(self._on_sendungen_alert_clicked)
        self._btn_sendungen_alert.hide()
        self._btn_digital_licenses_alert = self._toolbar.add_button(
            "digital_licenses_alert",
            "EXTERNE BESTELLUNG",
            tooltip="Bezahlte externe digitale Bestellungen anzeigen",
        )
        self._btn_digital_licenses_alert.setStyleSheet(
            "QPushButton {"
            "background-color: #b91c1c; color: white; border-radius: 6px;"
            "font-weight: bold; padding: 0 14px;"
            "}"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self._btn_digital_licenses_alert.clicked.connect(self._on_digital_licenses_alert_clicked)
        self._btn_digital_licenses_alert.hide()
        self._btn_mollie_alert = self._toolbar.add_button(
            "mollie_alert",
            "💳 MOLLIE AUTH",
            tooltip="Offene Mollie-Authorisierungen anzeigen",
        )
        self._btn_mollie_alert.setStyleSheet(
            "QPushButton {"
            "background-color: #b91c1c; color: white; border-radius: 6px;"
            "font-weight: bold; padding: 0 14px;"
            "}"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self._btn_mollie_alert.clicked.connect(self._on_mollie_alert_clicked)
        self._btn_mollie_alert.hide()
        layout.addWidget(self._toolbar)

        self._search = SearchBar("Suchen…", debounce_ms=220, min_chars=2, max_suggestions=12)
        self._search.set_suggestion_provider(self._invoice_search_suggestions)
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self._table = DataTable(_TABLE_COLUMNS)
        self._table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self._table.setStyleSheet(
            "QTableView::item:selected { background-color: rgba(29, 78, 216, 0.16); color: #0f172a; }"
            "QTableView::item:selected:focus { background-color: rgba(29, 78, 216, 0.26); color: #0f172a; }"
        )
        self._hints_delegate = _HintsIconDelegate(self._table)
        self._status_delegate = _InvoiceStatusDelegate(self._table)
        self._sevdesk_delegate = _SevdeskDraftActionDelegate(self._table)
        self._actions_delegate = _ActionsDelegate(self._table)
        self._fulfillment_delegate = _FulfillmentDelegate(self._table)
        sevdesk_col = _TABLE_COLUMNS.index("sevDesk")
        status_col = 3
        hint_col = _TABLE_COLUMNS.index("Hinweise")
        fulfillment_col = _TABLE_COLUMNS.index("FULFILLMENT")
        actions_col = _TABLE_COLUMNS.index("AKTIONEN")
        self._table.setItemDelegateForColumn(sevdesk_col, self._sevdesk_delegate)
        self._table.setItemDelegateForColumn(status_col, self._status_delegate)
        self._table.setItemDelegateForColumn(hint_col, self._hints_delegate)
        self._table.setItemDelegateForColumn(fulfillment_col, self._fulfillment_delegate)
        self._table.setItemDelegateForColumn(actions_col, self._actions_delegate)
        self._table.clicked.connect(self._on_table_clicked)
        self._table.viewport().installEventFilter(self)
        self._table.setMouseTracking(True)
        self._table.viewport().setMouseTracking(True)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setSectionsClickable(False)
        self._table.horizontalHeader().resizeSection(status_col, 48)
        self._table.horizontalHeader().resizeSection(hint_col, 150)
        self._table.horizontalHeader().resizeSection(actions_col, 120)
        self._table.horizontalHeader().resizeSection(fulfillment_col, 170)
        self._table.setColumnHidden(_TABLE_COLUMNS.index("ID"), True)
        left_layout.addWidget(self._table, stretch=1)

        load_more_row = QHBoxLayout()
        load_more_row.addStretch()
        self._btn_more = QPushButton("Weitere Rechnungen laden")
        self._btn_more.setToolTip(f"Naechste bis zu {_PAGE_SIZE} Entwuerfe anhaengen")
        self._btn_more.setFixedHeight(28)
        self._btn_more.setFixedWidth(150)
        self._btn_more.clicked.connect(self._load_more)
        load_more_row.addWidget(self._btn_more)
        left_layout.addLayout(load_more_row)

        splitter.addWidget(left_panel)

        # --- Structured detail panel ---
        detail_scroll = QScrollArea()
        self._detail_scroll = detail_scroll
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumWidth(360)
        detail_scroll.setMaximumWidth(460)

        detail_content = QWidget()
        detail_main = QVBoxLayout(detail_content)
        detail_main.setContentsMargins(8, 8, 8, 8)
        detail_main.setSpacing(10)

        self._gb_open = QGroupBox("OFFENE RECHNUNGEN")
        form_open = QFormLayout(self._gb_open)
        self._open_total = QLabel("—")
        self._open_physical = QLabel("—")
        self._open_digital = QLabel("—")
        self._open_with_ref = QLabel("—")
        self._open_plc = QLabel("—")
        self._open_note = QLabel("—")
        form_open.addRow("Gesamt:", self._open_total)
        form_open.addRow("Davon physisch:", self._open_physical)
        form_open.addRow("Davon digital-only:", self._open_digital)
        form_open.addRow("Mit Wix-Order-Ref:", self._open_with_ref)
        form_open.addRow("Mit PLC-Hinweis:", self._open_plc)
        form_open.addRow("Mit Käufernotiz:", self._open_note)
        detail_main.addWidget(self._gb_open)

        self._gb_open_products = QGroupBox("PRINT-PRODUKTE OFFEN")
        open_products_layout = QVBoxLayout(self._gb_open_products)
        open_products_layout.setContentsMargins(10, 8, 10, 10)
        open_products_header = QHBoxLayout()
        open_products_header.setContentsMargins(0, 0, 0, 0)
        open_products_header.addStretch(1)
        self._btn_print_all_products = QPushButton("PRINT ALL PRODUCTS")
        self._btn_print_all_products.setToolTip("Alle angezeigten Print-Produkte in der angezeigten Menge drucken")
        self._btn_print_all_products.setFixedHeight(26)
        self._btn_print_all_products.clicked.connect(self._on_print_all_open_products_clicked)
        open_products_header.addWidget(self._btn_print_all_products, alignment=Qt.AlignmentFlag.AlignRight)
        open_products_layout.addLayout(open_products_header)
        self._open_products_status = QLabel("Print-Produkte werden ermittelt...")
        self._open_products_status.setWordWrap(True)
        self._open_products_status.setStyleSheet("color: #cbd5e1;")
        open_products_layout.addWidget(self._open_products_status)
        self._open_products_rows = QWidget()
        self._open_products_rows_layout = QVBoxLayout(self._open_products_rows)
        self._open_products_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._open_products_rows_layout.setSpacing(6)
        open_products_layout.addWidget(self._open_products_rows)
        self._open_products_text = QTextBrowser()
        self._open_products_text.setReadOnly(True)
        self._open_products_text.hide()
        detail_main.addWidget(self._gb_open_products)

        self._gb_info = QGroupBox("INFO")
        info_layout = QGridLayout(self._gb_info)
        info_layout.setHorizontalSpacing(12)
        info_layout.setVerticalSpacing(8)
        info_layout.setColumnStretch(1, 1)
        self._dl_number = QLabel("—")
        self._dl_date = QLabel("—")
        self._dl_status = QLabel("—")
        self._dl_brutto = QLabel("—")
        self._dl_contact = QLabel("—")
        self._dl_contact.setWordWrap(True)
        self._dl_contact.setMaximumWidth(260)
        self._dl_country = QLabel("—")
        self._dl_order_ref = QLabel("—")
        self._wix_order_no = QLabel("—")
        self._wix_customer = QLabel("—")
        self._wix_customer_email = QLabel("—")
        info_labels = (
            self._dl_number,
            self._dl_date,
            self._dl_status,
            self._dl_brutto,
            self._dl_contact,
            self._dl_country,
            self._dl_order_ref,
            self._wix_order_no,
            self._wix_customer,
            self._wix_customer_email,
        )
        for lbl in info_labels:
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        info_fields = (
            ("Rechnung:", self._dl_number, 0, 0),
            ("Datum:", self._dl_date, 1, 0),
            ("Status:", self._dl_status, 2, 0),
            ("Brutto:", self._dl_brutto, 3, 0),
            ("Kunde:", self._dl_contact, 4, 0),
            ("Land:", self._dl_country, 5, 0),
            ("Order-Ref:", self._dl_order_ref, 6, 0),
        )
        for text, value_widget, row, col in info_fields:
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            info_layout.addWidget(label, row, col, alignment=Qt.AlignmentFlag.AlignTop)
            info_layout.addWidget(value_widget, row, col + 1, alignment=Qt.AlignmentFlag.AlignTop)
        self._gb_info.hide()
        detail_main.addWidget(self._gb_info)

        self._gb_shipping = QGroupBox("VERSANDADRESSE")
        shipping_layout = QVBoxLayout(self._gb_shipping)
        shipping_layout.setContentsMargins(12, 10, 12, 12)
        shipping_layout.setSpacing(6)
        shipping_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._shipping_status = QLabel("—")
        self._shipping_status.setWordWrap(True)
        self._shipping_status.setStyleSheet("color: #64748b;")
        self._shipping_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        shipping_layout.addWidget(self._shipping_status)
        shipping_row_wrap = QWidget(self._gb_shipping)
        shipping_row = QHBoxLayout(shipping_row_wrap)
        shipping_row.setContentsMargins(0, 0, 0, 0)
        shipping_row.setSpacing(8)
        self._shipping_editor = QPlainTextEdit()
        self._shipping_editor.setPlaceholderText("Lieferadresse Zeile für Zeile bearbeiten")
        self._shipping_editor.setMinimumHeight(104)
        self._shipping_editor.setMaximumHeight(150)
        self._shipping_editor.setMaximumWidth(300)
        self._shipping_editor.setMinimumWidth(240)
        self._shipping_editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._shipping_editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._shipping_editor.textChanged.connect(self._on_shipping_editor_changed)
        shipping_row.addWidget(self._shipping_editor, stretch=0)
        self._btn_print_label = QPushButton("")
        label_icon = Path(__file__).resolve().parents[5] / "icons" / "labelprint.png"
        if label_icon.exists():
            self._btn_print_label.setIcon(QIcon(str(label_icon)))
        self._btn_print_label.setToolTip("Label drucken")
        self._btn_print_label.setFixedSize(36, 36)
        self._btn_print_label.clicked.connect(self._on_print_label_clicked)
        self._btn_print_label.setEnabled(False)
        shipping_row.addWidget(self._btn_print_label, alignment=Qt.AlignmentFlag.AlignTop)
        shipping_row.addStretch()
        shipping_row_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        shipping_layout.addWidget(shipping_row_wrap, alignment=Qt.AlignmentFlag.AlignTop)
        self._gb_shipping.hide()
        detail_main.addWidget(self._gb_shipping)

        self._gb_note = QGroupBox("Käufernotiz")
        note_layout = QVBoxLayout(self._gb_note)
        self._dl_note = QLabel()
        self._dl_note.setWordWrap(True)
        note_layout.addWidget(self._dl_note)
        self._gb_note.hide()
        detail_main.addWidget(self._gb_note)

        self._gb_actions = QGroupBox("AKTIONEN")
        actions_layout = QGridLayout(self._gb_actions)
        actions_layout.setHorizontalSpacing(8)
        actions_layout.setVerticalSpacing(6)
        actions_layout.setColumnStretch(0, 1)
        actions_layout.setColumnStretch(1, 1)
        self._action_state = QLabel("Keine Rechnung ausgewählt")
        self._action_state.setWordWrap(True)
        self._action_state.setStyleSheet("color: #64748b;")
        actions_layout.addWidget(self._action_state, 0, 0, 1, 2)
        self._plc_last = QLabel("Letzter PLC-Druck: —")
        self._plc_last.setStyleSheet("color: #64748b; font-size: 11px;")
        actions_layout.addWidget(self._plc_last, 1, 0, 1, 2)
        self._action_state.hide()
        self._plc_last.hide()

        action_button_style = (
            "QPushButton { background-color: #334155; color: #f8fafc; border: 1px solid #64748b; "
            "border-radius: 5px; font-weight: 600; padding: 7px 10px; }"
            "QPushButton:hover { background-color: #475569; border-color: #94a3b8; }"
            "QPushButton:pressed { background-color: #1e293b; }"
            "QPushButton:disabled { background-color: #1f2937; color: #64748b; border-color: #334155; }"
        )
        self._btn_print = QPushButton("Rechnung drucken")
        self._btn_print.setStyleSheet(action_button_style)
        self._btn_print.clicked.connect(self._on_print_clicked)
        self._btn_print.setEnabled(False)
        actions_layout.addWidget(self._btn_print, 0, 0)

        self._btn_print_plc = QPushButton("PLC-Label drucken")
        self._btn_print_plc.setStyleSheet(action_button_style)
        self._btn_print_plc.clicked.connect(self._on_print_plc_selected)
        self._btn_print_plc.setEnabled(False)
        actions_layout.addWidget(self._btn_print_plc, 0, 1)

        self._btn_print_music = QPushButton("Noten drucken")
        self._btn_print_music.setStyleSheet(action_button_style)
        self._btn_print_music.clicked.connect(self._on_print_music_clicked)
        self._btn_print_music.setEnabled(False)
        actions_layout.addWidget(self._btn_print_music, 1, 0)

        self._btn_send_invoice = QPushButton("Rechnung senden")
        self._btn_send_invoice.setStyleSheet(action_button_style)
        self._btn_send_invoice.clicked.connect(self._on_send_invoice_clicked)
        self._btn_send_invoice.setEnabled(False)
        actions_layout.addWidget(self._btn_send_invoice, 1, 1)

        self._btn_open_plc_label = QPushButton("PLC-PDF öffnen")
        self._btn_open_plc_label.setStyleSheet(action_button_style)
        self._btn_open_plc_label.clicked.connect(self._on_open_plc_label_clicked)
        self._btn_open_plc_label.setEnabled(False)
        self._btn_open_plc_label.hide()
        actions_layout.addWidget(self._btn_open_plc_label, 2, 1)
        self._gb_actions.hide()
        detail_main.addWidget(self._gb_actions)

        self._gb_stuecke = QGroupBox("Produkte")
        self._stuecke_layout = QVBoxLayout(self._gb_stuecke)
        self._stuecke_layout.setSpacing(4)
        self._stuecke_hint = QLabel("—")
        self._stuecke_hint.setWordWrap(True)
        self._stuecke_layout.addWidget(self._stuecke_hint)
        self._piece_list = QListView(self._gb_stuecke)
        self._piece_list.setModel(self._piece_model)
        self._piece_list.setItemDelegate(self._piece_delegate)
        self._piece_list.setUniformItemSizes(False)
        self._piece_list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._piece_list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._piece_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._piece_list.setMinimumHeight(120)
        self._piece_list.hide()
        self._stuecke_layout.addWidget(self._piece_list)
        self._gb_stuecke.hide()
        detail_main.addWidget(self._gb_stuecke)

        self._gb_start_summary = QGroupBox("START-ZUSAMMENFASSUNG")
        summary_layout = QVBoxLayout(self._gb_start_summary)
        summary_layout.setContentsMargins(10, 8, 10, 10)
        self._start_summary_label = QLabel("")
        self._start_summary_label.setWordWrap(True)
        self._start_summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._start_summary_label.setStyleSheet("color: #0f172a; line-height: 1.25;")
        summary_layout.addWidget(self._start_summary_label)
        self._gb_start_summary.hide()
        detail_main.addWidget(self._gb_start_summary)
        detail_main.addStretch()
        detail_scroll.setWidget(detail_content)

        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([920, 390])
        layout.addWidget(splitter, stretch=1)

        self._overlay = ProgressOverlay(self)
        self._overlay.hide()

        self._search.search_changed.connect(self._on_search)
        sel = self._table.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_table_selection_changed)

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.printer_status_changed.connect(self._on_printer_status)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._printer_status_initialized:
            self._printer_status_initialized = True
            QTimer.singleShot(0, self._initialize_printer_status)
        if not self._did_initial_load:
            self._did_initial_load = True
            if self._has_sevdesk_token():
                self._reload_first_page()
        if self._deferred_load_payload is not None:
            rows, summaries, has_more, status_filter, append = self._deferred_load_payload
            self._deferred_load_payload = None
            self._apply_load_result_data(
                rows,
                summaries,
                has_more,
                status_filter,
                append,
                allow_background_prefetch=True,
            )
        if not self._badge_refresh_managed_externally:
            self._refresh_mollie_alert_count()
            self._mollie_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._post_load_prefetch_seq += 1
        self._mollie_timer.stop()
        self._stop_mollie_worker()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            global_pos = self.mapToGlobal(event.position().toPoint())
            if self._should_clear_selection_for_global_pos(global_pos):
                sel = self._table.selectionModel()
                if sel is not None:
                    sel.clearSelection()
                self._refresh_detail_for_selection()
        super().mousePressEvent(event)

    def _should_clear_selection_for_global_pos(self, global_pos: object) -> bool:
        if self._global_pos_inside_widget(self._table, global_pos):
            return False
        if self._global_pos_inside_widget(self._detail_scroll, global_pos):
            return False
        return True

    @staticmethod
    def _global_pos_inside_widget(widget: QWidget, global_pos: object) -> bool:
        local_pos = widget.mapFromGlobal(global_pos)  # type: ignore[arg-type]
        return widget.isVisible() and widget.rect().contains(local_pos)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.prepare_shutdown()
        super().closeEvent(event)

    def prepare_shutdown(self) -> bool:
        self._shutting_down = True
        self._post_load_prefetch_seq += 1
        self._hint_seq += 1
        self._wix_context_seq += 1
        self._detail_context_seq += 1
        self._mollie_timer.stop()
        self._wix_warm_queue.clear()
        self._wix_warm_inflight_refs.clear()
        if self._wix_warm_handle is not None:
            self._wix_warm_handle.cancel()
        if self._wix_context_handle is not None:
            self._wix_context_handle.cancel()
        self._background_jobs.cancel_owner(self)
        self._background_jobs.cancel_key("wix-warmup")
        self._stop_mollie_worker()
        return True

    def set_badge_refresh_managed_externally(self, enabled: bool) -> None:
        """Switch badge refresh to parent-managed mode to avoid duplicate polling."""
        self._badge_refresh_managed_externally = bool(enabled)
        if self._badge_refresh_managed_externally:
            self._mollie_timer.stop()
            self._stop_mollie_worker()

    def set_top_actions_managed_externally(self, enabled: bool) -> None:
        """Hide the embedded toolbar when the parent view owns those actions."""
        self._toolbar.setVisible(not bool(enabled))

    def reload_first_page(self) -> None:
        self._reload_first_page()

    def create_draft_from_wix_order(self) -> None:
        self._on_create_draft_clicked()

    def open_custom_label_dialog(self) -> None:
        self._on_custom_label_clicked()

    def open_manual_plc_label_dialog(self) -> None:
        self._on_manual_plc_label_clicked()

    def open_plc_statistics_dialog(self) -> None:
        self._on_plc_statistics_clicked()

    def open_special_order_dialog(self) -> None:
        self._on_special_order_clicked()

    def open_sendungen_dialog(self) -> int:
        dlg = OffeneSendungenDialog(self._container, self)
        dlg.exec()
        count = dlg.open_count()
        self.update_sendungen_alert_count(count)
        return count

    def open_digital_licenses_dialog(self) -> int:
        dlg = DigitalLicensesDialog(self._container, self)
        dlg.exec()
        count = dlg.open_count()
        self.update_digital_licenses_alert_count(count)
        return count

    def open_ueberweisungen_dialog(self) -> int:
        dlg = OffeneUeberweisungenDialog(self._container, self)
        dlg.exec()
        return dlg.open_count()

    def open_queue_dialog(self, queue_name: str, title: str, fallback_count: int = 0) -> None:
        from xw_office.ui.modules.rechnungen.tagesgeschaeft_view import QueuePopupDialog

        dlg = QueuePopupDialog(
            self._container,
            queue_name=queue_name,
            title=title,
            fallback_count=max(0, int(fallback_count)),
            parent=self,
        )
        dlg.exec()

    def show_start_summary(self, lines: list[str]) -> None:
        text = "\n".join(str(line).strip() for line in lines if str(line).strip())
        if not text:
            self._gb_start_summary.hide()
            self._start_summary_label.setText("")
            return
        self._start_summary_label.setText(text)
        self._gb_start_summary.show()

    def _stop_mollie_worker(self) -> None:
        # Never block module switches on background badge refresh.
        if self._mollie_badge_worker is None:
            return
        if not self._mollie_badge_worker.isRunning():
            self._mollie_badge_worker = None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_search(self, text: str) -> None:
        query = str(text or "").strip()
        if not query:
            self._search_active = False
            self._search_seq += 1
            self._restore_loaded_invoice_list()
            return
        self._search_active = True
        self._search_seq += 1
        seq = self._search_seq
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Suche in sevDesk läuft…", 2500)

        def job() -> tuple[list[dict[str, str]], list[InvoiceSummary], int, str, int]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            rows, summaries, searched_days = service.search_invoice_batch(query)
            return rows, summaries, searched_days, query, seq

        self._search_worker = BackgroundWorker(job)
        self._search_worker.signals.result.connect(self._on_search_result)
        self._search_worker.signals.error.connect(self._on_search_error)
        self._search_worker.signals.finished.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_printer_status(self, printing_allowed: bool) -> None:
        self._print_allowed = printing_allowed
        self._set_piece_print_controls_enabled(
            printing_allowed and not (self._product_print_worker is not None and self._product_print_worker.isRunning())
        )
        self._update_print_all_products_button()
        self._update_plc_controls()

    def _initialize_printer_status(self) -> None:
        service: PrinterStatusService = self._container.resolve(PrinterStatusService)
        self._on_printer_status(service.snapshot().printing_allowed)

    def _reload_first_page(self) -> None:
        self._next_offset = 0
        self._active_load_status = _DRAFT_STATUS
        self._draft_offset = 0
        self._open_offset = 0
        self._draft_has_more = False
        self._open_has_more = False
        self._open_loaded = False
        self._append_mode = False
        self._start_load(limit=_DRAFT_INITIAL_LOAD_LIMIT)

    def _load_more(self) -> None:
        if not self._has_sevdesk_token():
            return
        if self._active_load_status == _DRAFT_STATUS and not self._draft_has_more:
            self._active_load_status = _OPEN_STATUS
        self._append_mode = True
        self._start_load()

    def _start_load(self, *, limit: int | None = None) -> None:
        if not self._has_sevdesk_token():
            return
        if self._worker is not None and self._worker.isRunning():
            return

        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        status_filter = self._active_load_status
        page_limit = max(1, int(limit or _PAGE_SIZE))
        offset = (
            self._draft_offset if status_filter == _DRAFT_STATUS else self._open_offset
        ) if self._append_mode else 0
        append = self._append_mode
        self._load_started_at = time.perf_counter()
        logger.info(
            "Rechnungen phase=%s start limit=%s offset=%s append=%s",
            self._load_phase_label(status_filter),
            page_limit,
            offset,
            append,
        )

        self._overlay.show_with_message(
            "Rechnungen werden geladen…" if not append else "Weitere Rechnungen werden geladen…",
        )
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> tuple[list[dict[str, str]], list[InvoiceSummary], bool, int | None]:
            if status_filter == _DRAFT_STATUS:
                rows, sums = service.load_invoice_batch(
                    status=status_filter,
                    limit=page_limit,
                    offset=offset,
                )
            else:
                recent_loader = getattr(service, "load_recent_non_draft_batch", None)
                if callable(recent_loader):
                    rows, sums = recent_loader(limit=page_limit, offset=offset)
                else:
                    rows, sums = service.load_invoice_batch(
                        status=status_filter,
                        limit=page_limit,
                        offset=offset,
                    )
            has_more = len(sums) >= page_limit
            return rows, sums, has_more, status_filter

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_load_result)
        self._worker.signals.error.connect(self._on_load_error)
        self._worker.signals.finished.connect(self._on_load_finished)
        self._worker.start()

    @staticmethod
    def _blank_hint_patch() -> dict[str, object]:
        return {
            "Hinweise": "",
            "__icons__Hinweise": [],
            "__tooltip__Hinweise": "",
            "__fg__Hinweise": "",
        }

    def _prepare_rows_for_hint_prefetch(
        self,
        rows: list[dict[str, Any]],
        summaries: list[InvoiceSummary],
    ) -> None:
        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        for row, summary in zip(rows, summaries):
            row.update(self._blank_hint_patch())
            cached = service.get_cached_invoice_list_hints(summary.order_reference)
            if cached is not None:
                row.update(cached.as_row_patch())

    def _current_sevdesk_token(self) -> str:
        service: SecretService = self._container.resolve(SecretService)
        return service.get_secret("SEVDESK_API_TOKEN").strip()

    def _has_sevdesk_token(self) -> bool:
        return bool(self._current_sevdesk_token())

    def _on_load_result(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 4:
            logger.warning("Unexpected invoice load payload: %s", type(payload))
            return
        rows_obj, sums_obj, has_more_obj, status_obj = payload
        if not isinstance(rows_obj, list) or not isinstance(sums_obj, list):
            return
        rows: list[dict[str, Any]] = [r for r in rows_obj if isinstance(r, dict)]
        summaries: list[InvoiceSummary] = [s for s in sums_obj if isinstance(s, InvoiceSummary)]
        has_more = bool(has_more_obj)
        status_filter = None if status_obj is None else int(status_obj)
        elapsed_ms = int((time.perf_counter() - self._load_started_at) * 1000) if self._load_started_at else 0
        logger.info(
            "Rechnungen phase=%s result rows=%s has_more=%s elapsed_ms=%s",
            self._load_phase_label(status_filter),
            len(summaries),
            has_more,
            elapsed_ms,
        )
        append = bool(self._append_mode)
        if not self.isVisible():
            self._deferred_load_payload = (rows, summaries, has_more, status_filter, append)
            self._pending_auto_open_load = (
                status_filter == _DRAFT_STATUS
                and not has_more
                and not self._open_loaded
                and not self._search_active
            )
            self._append_mode = False
            signals: AppSignals = self._container.resolve(AppSignals)
            signals.status_message.emit(
                f"{len(rows)} Rechnungen im Hintergrund geladen",
                3500,
            )
            return

        self._apply_load_result_data(
            rows,
            summaries,
            has_more,
            status_filter,
            append,
            allow_background_prefetch=True,
        )

    def _apply_load_result_data(
        self,
        rows: list[dict[str, Any]],
        summaries: list[InvoiceSummary],
        has_more: bool,
        status_filter: int | None,
        append: bool,
        *,
        allow_background_prefetch: bool,
    ) -> None:
        self._prepare_rows_for_hint_prefetch(rows, summaries)

        if append:
            combined_rows = self._table.source_rows_data() + list(rows)
            combined_summaries = list(self._summaries) + list(summaries)
            sorted_rows, sorted_summaries = self._sort_rows_by_actuality(
                combined_rows,
                combined_summaries,
            )
            self._table.set_data(sorted_rows)
            self._summaries = sorted_summaries
        else:
            sorted_rows, sorted_summaries = self._sort_rows_by_actuality(rows, summaries)
            self._table.set_data(sorted_rows)
            self._summaries = sorted_summaries
            self._loaded_rows = sorted_rows
            self._loaded_summaries = sorted_summaries
            self._loaded_has_more = has_more

        if status_filter == _DRAFT_STATUS:
            self._draft_offset = sum(
                1 for summary in self._summaries if summary.status_code == _DRAFT_STATUS
            )
            self._draft_has_more = has_more
        elif status_filter == _OPEN_STATUS:
            self._open_loaded = True
            self._open_offset = sum(
                1 for summary in self._summaries if summary.status_code != _DRAFT_STATUS
            )
            self._open_has_more = has_more

        auto_load_open = (
            status_filter == _DRAFT_STATUS
            and not self._draft_has_more
            and not self._open_loaded
            and not self._search_active
        )
        self._search.refresh_suggestions()
        self._rebuild_search_index()
        self._apply_table_column_layout()
        self._table_layout_initialized = True
        self._schedule_open_overview_refresh()

        self._next_offset = len(self._summaries)
        self._update_load_more_button()

        signals: AppSignals = self._container.resolve(AppSignals)
        mode = "angehaengt" if append else "geladen"
        signals.status_message.emit(
            f"{len(rows)} Rechnungen {mode} ({self._next_offset} gesamt in Liste)",
            5000,
        )
        self._append_mode = False
        self._refresh_detail_for_selection()
        if allow_background_prefetch:
            self._schedule_post_load_prefetch(status_filter, list(self._summaries))
        if auto_load_open:
            logger.info("Rechnungen auto-open-load queued limit=%s", _OPEN_AUTO_LOAD_LIMIT)
            self._pending_auto_open_load = True

    def _sort_rows_by_actuality(
        self,
        rows: list[dict[str, Any]],
        summaries: list[InvoiceSummary],
    ) -> tuple[list[dict[str, Any]], list[InvoiceSummary]]:
        if not rows or not summaries:
            return list(rows), list(summaries)

        count = min(len(rows), len(summaries))
        paired = list(zip(rows[:count], summaries[:count], strict=False))
        paired.sort(
            key=lambda pair: self._summary_actuality_key(pair[1]),
            reverse=True,
        )

        sorted_rows = [row for row, _summary in paired]
        sorted_summaries = [summary for _row, summary in paired]

        if len(summaries) > count:
            sorted_summaries.extend(summaries[count:])
            sorted_rows.extend(summary.as_table_row() for summary in summaries[count:])
        elif len(rows) > count:
            sorted_rows.extend(rows[count:])

        return sorted_rows, sorted_summaries

    def _summary_actuality_key(self, summary: InvoiceSummary) -> tuple[float, int]:
        raw_date = str(summary.invoice_date or "").strip()
        timestamp = 0.0
        if raw_date:
            normalized = raw_date.replace("Z", "+00:00")
            try:
                timestamp = datetime.fromisoformat(normalized).timestamp()
            except ValueError:
                timestamp = 0.0
        id_rank = int(summary.id) if str(summary.id).isdigit() else -1
        return (timestamp, id_rank)

    def _schedule_open_overview_refresh(self) -> None:
        def run_refresh() -> None:
            if not self.isVisible():
                return
            self._refresh_open_invoice_overview()

        QTimer.singleShot(0, run_refresh)

    def _schedule_post_load_prefetch(self, status_filter: int | None, summaries: list[InvoiceSummary]) -> None:
        self._post_load_prefetch_seq += 1
        seq = self._post_load_prefetch_seq
        snapshot = list(summaries)

        def run_prefetch() -> None:
            if seq != self._post_load_prefetch_seq:
                return
            if not self.isVisible() or self._search_active:
                return
            if self._worker is not None and self._worker.isRunning():
                return
            self._warm_wix_context_for_summaries(snapshot)
            if status_filter != _OPEN_STATUS:
                self._restart_hint_prefetch()

        # Delay side-jobs slightly so navigation/interaction stays snappy
        # right after a fresh table update.
        QTimer.singleShot(2500, run_prefetch)

    def _submit_side_job(
        self,
        *,
        coalesce_key: str,
        priority: int,
        start_fn: Callable[[], BackgroundWorker | None],
        can_start: Callable[[], bool] | None = None,
    ) -> None:
        self._background_jobs.submit(
            queue=_SIDE_JOB_QUEUE,
            priority=priority,
            coalesce_key=coalesce_key,
            start_fn=start_fn,
            can_start=can_start,
        )

    def _update_load_more_button(self) -> None:
        if self._search_active:
            self._btn_more.setEnabled(False)
            return
        if self._active_load_status == _DRAFT_STATUS:
            if self._draft_has_more:
                self._btn_more.setText("Weitere Rechnungen laden")
                self._btn_more.setToolTip(f"Naechste bis zu {_PAGE_SIZE} Entwuerfe anhaengen")
                self._btn_more.setEnabled(True)
            elif not self._open_loaded:
                self._btn_more.setText("Weitere Rechnungen laden")
                self._btn_more.setToolTip("Neueste Rechnungen laden")
                self._btn_more.setEnabled(True)
            else:
                self._btn_more.setText("Keine weiteren")
                self._btn_more.setToolTip("Keine weiteren Rechnungen in dieser Ansicht")
                self._btn_more.setEnabled(False)
            return
        if self._open_has_more:
            self._btn_more.setText("Weitere Rechnungen laden")
            self._btn_more.setToolTip(f"Naechste bis zu {_PAGE_SIZE} neueste Rechnungen anhaengen")
            self._btn_more.setEnabled(True)
        else:
            self._btn_more.setText("Keine weiteren")
            self._btn_more.setToolTip("Keine weiteren neueren Rechnungen")
            self._btn_more.setEnabled(False)

    def _apply_table_column_layout(self) -> None:
        if self._table_layout_initialized:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        for idx in range(len(_TABLE_COLUMNS)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
        # Keep layout deterministic and cheap; ResizeToContents on large batches
        # can stall the UI thread for seconds.
        self._table.setColumnWidth(0, 120)  # sevDesk
        self._table.setColumnWidth(1, 96)   # WIX
        self._table.setColumnWidth(2, 86)   # Datum
        self._table.setColumnWidth(3, 52)   # Status icon
        self._table.setColumnWidth(4, 112)  # Betrag
        self._table.setColumnWidth(5, 260)  # Kunde
        self._table.setColumnWidth(6, 160)  # Hinweise
        self._table.setColumnWidth(7, 124)  # Aktionen
        self._table.setColumnWidth(8, 178)  # Fulfillment

    def _refresh_mollie_alert_count(self) -> None:
        self._background_jobs.submit(
            queue="badge-refresh",
            priority=20,
            coalesce_key="rechnungen-mollie-badges",
            start_fn=self._create_mollie_badge_worker,
            can_start=lambda: self._mollie_badge_worker is None or not self._mollie_badge_worker.isRunning(),
        )

    def _create_mollie_badge_worker(self) -> BackgroundWorker | None:
        if self._mollie_badge_worker is not None and self._mollie_badge_worker.isRunning():
            return None

        def job() -> dict[str, int]:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            counts = service.load_counts(open_invoice_count=0)
            sendungen_service: OffeneSendungenService = self._container.resolve(OffeneSendungenService)
            digital_licenses: DigitalLicenseService = self._container.resolve(DigitalLicenseService)
            return {
                "mollie": max(0, int(counts.get("mollie", 0))),
                "sendungen": max(0, int(sendungen_service.open_count())),
                "digital_licenses": max(0, int(digital_licenses.open_count(limit=30, use_cache=True))),
            }

        self._mollie_badge_worker = BackgroundWorker(job)
        self._mollie_badge_worker.signals.result.connect(self._on_mollie_badge_result)
        self._mollie_badge_worker.signals.finished.connect(lambda: setattr(self, "_mollie_badge_worker", None))
        return self._mollie_badge_worker

    def _on_mollie_badge_result(self, result: object) -> None:
        if isinstance(result, dict):
            mollie = max(0, int(result.get("mollie") or 0))
            sendungen = max(0, int(result.get("sendungen") or 0))
            digital_licenses = max(0, int(result.get("digital_licenses") or 0))
        else:
            mollie = max(0, int(result)) if isinstance(result, int) else 0
            sendungen = 0
            digital_licenses = 0
        self.update_mollie_alert_count(mollie)
        self.update_sendungen_alert_count(sendungen)
        self.update_digital_licenses_alert_count(digital_licenses)

    def update_mollie_alert_count(self, count: int) -> None:
        self._mollie_alert_count = max(0, int(count))
        if self._mollie_alert_count > 0:
            self._btn_mollie_alert.setText(f"💳 MOLLIE AUTH ({self._mollie_alert_count})")
            self._btn_mollie_alert.show()
            return
        self._btn_mollie_alert.hide()

    def update_sendungen_alert_count(self, count: int) -> None:
        self._sendungen_alert_count = max(0, int(count))
        if self._sendungen_alert_count > 0:
            self._btn_sendungen_alert.setText(f"✉ OFFENE SENDUNGEN ({self._sendungen_alert_count})")
            self._btn_sendungen_alert.show()
            return
        self._btn_sendungen_alert.hide()

    def update_digital_licenses_alert_count(self, count: int) -> None:
        self._digital_licenses_alert_count = max(0, int(count))
        if self._digital_licenses_alert_count > 0:
            self._btn_digital_licenses_alert.setText(
                f"EXTERNE BESTELLUNG ({self._digital_licenses_alert_count})"
            )
            self._btn_digital_licenses_alert.show()
            return
        self._btn_digital_licenses_alert.hide()

    def _on_mollie_alert_clicked(self) -> None:
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.navigate_to_module.emit(ModuleKey.MOLLIE.value)

    def _on_sendungen_alert_clicked(self) -> None:
        dlg = OffeneSendungenDialog(self._container, self)
        dlg.exec()
        self.update_sendungen_alert_count(dlg.open_count())

    def _on_digital_licenses_alert_clicked(self) -> None:
        dlg = DigitalLicensesDialog(self._container, self)
        dlg.exec()
        self.update_digital_licenses_alert_count(dlg.open_count())

    def _on_special_order_clicked(self) -> None:
        dlg = SpecialOrderDialog(self._container, self)
        dlg.exec()

    def _selected_summary(self) -> InvoiceSummary | None:
        row = self._table.selected_source_row()
        if row is None or row < 0 or row >= len(self._summaries):
            return None
        return self._summaries[row]

    def selected_summaries(self) -> list[InvoiceSummary]:
        """Return selected invoice summaries in source-model order."""
        selected: list[InvoiceSummary] = []
        for row in self._table.selected_source_rows():
            if 0 <= row < len(self._summaries):
                selected.append(self._summaries[row])
        return selected

    def _require_selected_invoice(self) -> InvoiceSummary | None:
        summary = self._selected_summary()
        if summary is not None:
            return summary
        QMessageBox.information(
            self,
            "Aktion",
            "Bitte zuerst eine Rechnung in der Liste auswählen.",
        )
        return None

    def _invoice_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 2:
            return []
        exact: list[str] = []
        starts: list[str] = []
        contains: list[str] = []
        for row in self._search_index:
            inv = row.get("inv", "")
            customer = row.get("customer", "")
            order_nr = row.get("order", "")
            label = row.get("label", "")

            if inv == q or customer == q or order_nr == q:
                exact.append(label)
                continue
            if inv.startswith(q) or customer.startswith(q) or order_nr.startswith(q):
                starts.append(label)
                continue
            if q in inv or q in customer or q in order_nr:
                contains.append(label)

        out: list[str] = []
        for bucket in (exact, starts, contains):
            for item in bucket:
                if item not in out:
                    out.append(item)
                if len(out) >= 12:
                    return out
        return out

    def _rebuild_search_index(self) -> None:
        self._search_index = []
        for summary in self._summaries:
            inv = str(summary.invoice_number or "").strip().lower()
            customer = str(summary.contact_name or "").strip().lower()
            order_ref = str(summary.order_reference or "").strip().lower()
            numeric_order = "".join(ch for ch in order_ref if ch.isdigit())
            order_search = numeric_order if numeric_order else order_ref
            label = f"{summary.invoice_number or '—'} - {summary.contact_name or '—'}"
            self._search_index.append(
                {
                    "inv": inv,
                    "customer": customer,
                    "order": order_search,
                    "label": label,
                }
            )

    def _on_load_error(self, exc: Exception) -> None:
        logger.error("Invoice load failed: %s", exc)
        self._pending_auto_open_load = False
        QMessageBox.warning(
            self,
            "Fehler",
            f"Rechnungen konnten nicht geladen werden:\n\n{exc}",
        )
        self._append_mode = False

    def _on_load_finished(self) -> None:
        self._overlay.hide()
        self._worker = None
        if not self.isVisible():
            return
        if self._pending_auto_open_load and not self._search_active:
            self._pending_auto_open_load = False
            self._active_load_status = _OPEN_STATUS
            self._append_mode = True
            logger.info("Rechnungen auto-open-load starting after draft worker finished")
            self._start_load(limit=_OPEN_AUTO_LOAD_LIMIT)

    def _restore_loaded_invoice_list(self) -> None:
        self._table.set_data(self._loaded_rows)
        self._summaries = list(self._loaded_summaries)
        self._update_load_more_button()
        self._search.refresh_suggestions()
        self._rebuild_search_index()
        self._refresh_detail_for_selection()
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"Rechnungen zurückgesetzt ({len(self._loaded_summaries)} in geladener Liste)",
            3000,
        )

    def _on_search_result(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 5:
            return
        rows_obj, summaries_obj, searched_days_obj, query_obj, seq_obj = payload
        if int(seq_obj) != self._search_seq:
            return
        rows = [row for row in rows_obj if isinstance(row, dict)] if isinstance(rows_obj, list) else []
        summaries = [summary for summary in summaries_obj if isinstance(summary, InvoiceSummary)] if isinstance(summaries_obj, list) else []
        searched_days = max(100, int(searched_days_obj or 100))
        query = str(query_obj or "").strip()
        self._prepare_rows_for_hint_prefetch(rows, summaries)
        self._table.set_data(rows)
        self._summaries = summaries
        self._btn_more.setEnabled(False)
        self._search.refresh_suggestions()
        self._rebuild_search_index()
        if len(summaries) == 1:
            self._table.select_source_row(0)
        else:
            self._refresh_detail_for_selection()
        self._restart_hint_prefetch()
        signals: AppSignals = self._container.resolve(AppSignals)
        if summaries:
            signals.status_message.emit(
                f"{len(summaries)} Treffer für '{query}' in den letzten {searched_days} Tagen",
                5000,
            )
        else:
            signals.status_message.emit(
                f"Keine Treffer für '{query}' nach Suche über {searched_days} Tage",
                5000,
            )

    def _on_search_error(self, exc: Exception) -> None:
        logger.error("Invoice search failed: %s", exc)
        QMessageBox.warning(
            self,
            "Suche",
            f"Rechnungssuche fehlgeschlagen:\n\n{exc}",
        )

    def _on_search_finished(self) -> None:
        self._search_worker = None

    def _refresh_open_invoice_overview(self) -> None:
        open_rows = [s for s in self._summaries if s.status_code == 100]
        try:
            wix_client: WixOrdersClient | None = self._container.resolve(WixOrdersClient)
        except Exception:  # noqa: BLE001 - overview still works with UI cache only.
            wix_client = None
        overview = overview_from_visible_summaries(
            open_rows,
            digital_cache=self._wix_digital_cache,
            wix_client=wix_client,
            include_print_products=False,
        )

        if overview.total == 0:
            self._apply_open_invoice_overview(overview)
            self._open_physical.setText("0")
            self._open_digital.setText("0")
            self._open_overview_key = ""
            self._open_overview_cached_physical = 0
            self._open_overview_cached_digital = 0
            self._open_overview_cached_note = 0
            self._open_overview_cached_plc = 0
            self._open_overview_complete = True
            self._open_overview_products_text = ""
            self._open_overview_products = []
            return

        if overview.key and overview.key == self._open_overview_key and self._open_overview_complete:
            for key, value in overview.cache_updates.items():
                self._wix_digital_cache[str(key)] = bool(value)
            self._open_total.setText(str(max(0, overview.total)))
            self._open_with_ref.setText(str(max(0, overview.with_ref)))
            self._open_physical.setText(str(self._open_overview_cached_physical))
            self._open_digital.setText(str(self._open_overview_cached_digital))
            self._open_plc.setText(str(self._open_overview_cached_plc))
            self._open_note.setText(str(self._open_overview_cached_note))
            if self._open_overview_products or self._print_products_last_run:
                cached_overview = OpenInvoiceOverview(
                    key=self._open_overview_key,
                    total=overview.total,
                    with_ref=overview.with_ref,
                    physical=self._open_overview_cached_physical,
                    digital=self._open_overview_cached_digital,
                    unknown=0,
                    with_note=self._open_overview_cached_note,
                    plc=self._open_overview_cached_plc,
                    complete=True,
                    print_products=list(self._open_overview_products),
                )
                self._render_open_print_products(self._print_product_display_overview(cached_overview))
            return

        self._apply_open_invoice_overview(overview)
        has_refs = any(str(summary.order_reference or "").strip() for summary in open_rows)
        if has_refs:
            self._open_overview_products_text = "Print-Produkte werden ermittelt..."
            self._open_overview_products = []
            if not self._print_products_last_run:
                self._set_open_products_message("Print-Produkte werden ermittelt...")
            self._start_open_invoice_overview(open_rows)

    def _start_open_invoice_overview(
        self,
        open_rows: list[InvoiceSummary],
    ) -> None:
        self._pending_open_overview_rows = list(open_rows)
        self._submit_side_job(
            coalesce_key="open-overview",
            priority=_PRIORITY_OPEN_OVERVIEW,
            start_fn=self._create_open_overview_worker,
            can_start=self._can_run_open_overview_job,
        )

    def _can_run_open_overview_job(self) -> bool:
        if self._open_overview_worker is not None and self._open_overview_worker.isRunning():
            return False
        if self._wix_context_worker is not None and self._wix_context_worker.isRunning():
            return False
        if self._invoice_detail_worker is not None and self._invoice_detail_worker.isRunning():
            return False
        return True

    def _create_open_overview_worker(self) -> BackgroundWorker | None:
        open_rows = list(self._pending_open_overview_rows)
        if not open_rows:
            return None
        refs = [s.order_reference.strip() for s in open_rows if s.order_reference.strip()]
        if not refs:
            self._pending_open_overview_rows = []
            return None
        self._open_overview_seq += 1
        seq = self._open_overview_seq
        snapshot = list(open_rows)
        digital_cache = dict(self._wix_digital_cache)
        self._pending_open_overview_rows = []
        logger.debug(
            "Rechnungen phase=open-overview start rows=%s refs=%s",
            len(snapshot),
            len(refs),
        )

        def job() -> OpenInvoiceOverview:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            wix_client: WixOrdersClient = self._container.resolve(WixOrdersClient)
            return resolve_open_invoice_overview(
                snapshot,
                seq=seq,
                invoice_service=service,
                wix_client=wix_client,
                digital_cache=digital_cache,
                sku_filter=service.is_flagged_sku,
            )

        self._open_overview_worker = BackgroundWorker(job)
        self._open_overview_worker.signals.result.connect(self._on_open_overview_result)
        self._open_overview_worker.signals.error.connect(self._on_open_overview_error)
        self._open_overview_worker.signals.finished.connect(self._on_open_overview_finished)
        return self._open_overview_worker

    def _on_open_overview_result(self, payload: object) -> None:
        overview = overview_payload_from_object(payload)
        if overview is None:
            return
        if overview.seq != self._open_overview_seq:
            return
        logger.debug(
            "Rechnungen phase=open-overview result total=%s physical=%s digital=%s unknown=%s",
            overview.total,
            overview.physical,
            overview.digital,
            overview.unknown,
        )
        self._apply_open_invoice_overview(overview)

    def _on_open_overview_error(self, exc: Exception) -> None:
        logger.warning("Open-overview digital classification failed: %s", exc)
        with_ref = int(self._open_with_ref.text() or "0") if self._open_with_ref.text().isdigit() else 0
        self._open_overview_cached_physical = 0
        self._open_overview_cached_digital = 0
        self._open_overview_complete = False
        suffix = "+" if with_ref else ""
        self._open_physical.setText(f"0{suffix}")
        self._open_digital.setText(f"0{suffix}")

    def _on_open_overview_finished(self) -> None:
        self._open_overview_worker = None
        if self._pending_open_overview_rows:
            self._submit_side_job(
                coalesce_key="open-overview",
                priority=_PRIORITY_OPEN_OVERVIEW,
                start_fn=self._create_open_overview_worker,
                can_start=self._can_run_open_overview_job,
            )

    def _apply_open_invoice_overview(self, overview: OpenInvoiceOverview) -> None:
        for key, value in overview.cache_updates.items():
            self._wix_digital_cache[str(key)] = bool(value)
        self._open_total.setText(str(max(0, overview.total)))
        self._open_with_ref.setText(str(max(0, overview.with_ref)))
        self._open_physical.setText(f"{max(0, overview.physical)}{overview.suffix}")
        self._open_digital.setText(f"{max(0, overview.digital)}{overview.suffix}")
        self._open_note.setText(str(max(0, overview.with_note)))
        self._open_plc.setText(str(max(0, overview.plc)))
        self._open_overview_key = overview.key
        self._open_overview_cached_physical = max(0, overview.physical)
        self._open_overview_cached_digital = max(0, overview.digital)
        self._open_overview_cached_note = max(0, overview.with_note)
        self._open_overview_cached_plc = max(0, overview.plc)
        self._open_overview_complete = overview.complete
        self._open_overview_products_text = self._format_open_print_products(overview)
        self._open_overview_products = list(overview.print_products)
        self._merge_session_print_products(overview.print_products)
        self._render_open_print_products(self._print_product_display_overview(overview))

    def mark_print_products_last_run(self) -> None:
        """Keep the accumulated product list visible after a completed START run."""
        self._print_products_last_run = True
        self._gb_open_products.setTitle("PRINT PRODUKTE (last run)")
        overview = OpenInvoiceOverview(
            key="session-last-run",
            total=0,
            with_ref=0,
            physical=0,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=list(self._session_print_products),
        )
        self._render_open_print_products(overview)

    def _merge_session_print_products(self, products: list[PrintProductAggregate]) -> None:
        """Append new products and retain the largest quantity seen this session."""
        positions = {
            self._print_product_session_key(item): index
            for index, item in enumerate(self._session_print_products)
        }
        for item in products:
            key = self._print_product_session_key(item)
            index = positions.get(key)
            if index is None:
                positions[key] = len(self._session_print_products)
                self._session_print_products.append(item)
                continue
            previous = self._session_print_products[index]
            if int(item.quantity or 0) > int(previous.quantity or 0):
                self._session_print_products[index] = item

    @staticmethod
    def _print_product_session_key(item: PrintProductAggregate) -> tuple[str, str, str, str]:
        return (
            str(item.sku or "").strip().casefold(),
            str(item.title or "").strip().casefold(),
            str(item.description or "").strip().casefold(),
            str(item.category_label or "").strip().casefold(),
        )

    def _print_product_display_overview(self, overview: OpenInvoiceOverview) -> OpenInvoiceOverview:
        if not self._print_products_last_run:
            return overview
        return OpenInvoiceOverview(
            key=overview.key,
            total=overview.total,
            with_ref=overview.with_ref,
            physical=overview.physical,
            digital=overview.digital,
            unknown=0,
            with_note=overview.with_note,
            plc=overview.plc,
            complete=overview.complete,
            cache_updates=overview.cache_updates,
            print_products=list(self._session_print_products),
            seq=overview.seq,
        )

    def _clear_open_print_product_rows(self) -> None:
        while self._open_products_rows_layout.count():
            item = self._open_products_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_open_products_message(self, message: str) -> None:
        self._clear_open_print_product_rows()
        self._open_products_status.setText(message)
        self._open_products_status.show()
        self._open_products_text.setPlainText(message)

    def _render_open_print_products(self, overview: OpenInvoiceOverview) -> None:
        if overview.unknown and not overview.print_products:
            self._set_open_products_message("Print-Produkte werden ermittelt...")
            self._update_print_all_products_button()
            return
        if not overview.print_products:
            self._set_open_products_message("Keine geflaggten Print-Produkte in den offenen Rechnungen gefunden.")
            self._update_print_all_products_button()
            return
        self._clear_open_print_product_rows()
        self._open_products_status.hide()
        plain_lines: list[str] = []
        for item in overview.print_products:
            row = self._build_open_print_product_row(item)
            self._open_products_rows_layout.addWidget(row)
            plain_lines.append(self._plain_open_print_product_line(item))
        if overview.unknown:
            note = QLabel("Weitere Print-Produkte werden noch ermittelt.")
            note.setStyleSheet("color: #94a3b8; font-size: 11px;")
            self._open_products_rows_layout.addWidget(note)
            plain_lines.append("Weitere Print-Produkte werden noch ermittelt.")
        self._open_products_rows_layout.addStretch(1)
        self._open_products_text.setPlainText("\n".join(plain_lines))
        self._update_print_all_products_button()

    def _displayed_print_products(self) -> list[PrintProductAggregate]:
        products = self._session_print_products if self._print_products_last_run else self._open_overview_products
        return [item for item in products if str(item.sku or "").strip()]

    def _update_print_all_products_button(self) -> None:
        if not hasattr(self, "_btn_print_all_products"):
            return
        running = self._product_print_worker is not None and self._product_print_worker.isRunning()
        self._btn_print_all_products.setEnabled(
            bool(self._print_allowed and self._displayed_print_products() and not running)
        )

    @staticmethod
    def _print_all_products_key(products: list[PrintProductAggregate]) -> tuple[tuple[str, str, str, int], ...]:
        return tuple(
            (
                str(item.sku or "").strip().casefold(),
                str(item.title or "").strip().casefold(),
                str(item.description or "").strip().casefold(),
                max(1, int(item.quantity or 1)),
            )
            for item in products
        )

    def _on_print_all_open_products_clicked(self) -> None:
        if not self._print_allowed or (self._product_print_worker is not None and self._product_print_worker.isRunning()):
            return
        products = self._displayed_print_products()
        if not products:
            QMessageBox.information(
                self,
                "PRINT ALL PRODUCTS",
                "Keine Print-Produkte in der aktuellen Liste gefunden.",
            )
            return
        products_key = self._print_all_products_key(products)
        if products_key == self._last_print_all_products_key:
            answer = QMessageBox.question(
                self,
                "PRINT ALL PRODUCTS",
                "Produkte bereits gedruckt.\n\nErneut drucken?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        from xw_office.ui.modules.rechnungen.print_dialog import (
            _configure_missing_piece_print,
            prepare_piece_pdf_print,
        )

        prepared_jobs: list[tuple[PieceBlock, int, Callable[[], None]]] = []
        for item in products:
            block = self._piece_block_from_open_product(item)
            qty = max(1, int(item.quantity or 1))
            if not self._open_print_product_ready(item) and not _configure_missing_piece_print(
                self,
                self._container,
                block,
            ):
                signals: AppSignals = self._container.resolve(AppSignals)
                signals.status_message.emit(
                    f"PRINT ALL PRODUCTS abgebrochen: {block.sku} wurde nicht konfiguriert.",
                    8000,
                )
                return
            job = prepare_piece_pdf_print(self, self._container, piece=block, copies=qty, wait=True)
            if job is None:
                signals: AppSignals = self._container.resolve(AppSignals)
                signals.status_message.emit(
                    f"PRINT ALL PRODUCTS abgebrochen: {block.sku} ist nicht druckbereit.",
                    8000,
                )
                return
            prepared_jobs.append((block, qty, job))

        if not prepared_jobs:
            return

        self._btn_print_all_products.setEnabled(False)
        self._set_piece_print_controls_enabled(False)
        total_copies = sum(qty for _block, qty, _job in prepared_jobs)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"PRINT ALL PRODUCTS gestartet: {len(prepared_jobs)} Produkt(e), {total_copies}x.",
            5000,
        )

        def worker_job() -> dict[str, object]:
            printed: list[str] = []
            warnings: list[str] = []
            for block, qty, job in prepared_jobs:
                job()
                printed.append(f"{block.sku} ({qty}x)")
                if block.product is None or not str(block.product.sevdesk_part_id or "").strip():
                    warnings.append(f"{block.sku}: kein sevDesk-Part fuer Bestandsbuchung hinterlegt")
                    continue
                try:
                    engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
                    new_stock = engine.record_print_and_update_sevdesk(block, qty)
                    self._container.resolve(InventoryService).set_product_stock(block.sku, new_stock)
                except Exception as exc:
                    logger.warning("Stock update after PRINT ALL PRODUCTS failed for %s: %s", block.sku, exc)
                    warnings.append(f"{block.sku}: {exc}")
            return {
                "sku": f"{len(printed)} Produkt(e)",
                "quantity": total_copies,
                "stock_warning": "\n".join(warnings),
                "printed": ", ".join(printed),
                "print_all_key": products_key,
            }

        self._product_print_worker = BackgroundWorker(worker_job)
        self._product_print_worker.signals.result.connect(self._on_product_print_result)
        self._product_print_worker.signals.result.connect(self._on_print_all_open_products_result)
        self._product_print_worker.signals.error.connect(self._on_product_print_error)
        self._product_print_worker.signals.finished.connect(self._on_product_print_finished)
        self._product_print_worker.start()

    def _on_print_all_open_products_result(self, payload: object) -> None:
        if isinstance(payload, dict) and isinstance(payload.get("print_all_key"), tuple):
            self._last_print_all_products_key = payload["print_all_key"]

    def _build_open_print_product_row(self, item: PrintProductAggregate) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            "QWidget { background-color: #1f2933; border: 1px solid #334155; border-radius: 4px; }"
            "QLabel { border: none; background: transparent; }"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        qty_label = QLabel(f"{max(1, int(item.quantity or 1))}x")
        qty_label.setStyleSheet("color: #ffffff; font-weight: 700;")
        qty_label.setMinimumWidth(32)
        layout.addWidget(qty_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        title = QLabel(str(item.title or item.sku or "Unbenanntes Produkt"))
        title.setWordWrap(True)
        title.setStyleSheet("color: #ffffff; font-weight: 700;")
        description = QLabel(self._open_product_description(item))
        description.setWordWrap(True)
        description.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        text_col.addWidget(title)
        text_col.addWidget(description)
        layout.addLayout(text_col, stretch=1)

        sku_label = QLabel(str(item.sku or "-"))
        sku_label.setStyleSheet("color: #93c5fd;")
        sku_label.setMinimumWidth(74)
        layout.addWidget(sku_label)

        action = QToolButton()
        action.setFixedSize(32, 28)
        action.setEnabled(self._print_allowed)
        action.setStyleSheet(
            "QToolButton { background-color: #334155; border: 1px solid #64748b; border-radius: 4px; }"
            "QToolButton:hover { background-color: #475569; border-color: #94a3b8; }"
            "QToolButton:disabled { background-color: #1f2937; border-color: #334155; }"
        )
        if self._open_print_product_ready(item):
            action.setIcon(QIcon(str(Path(__file__).resolve().parents[5] / "icons" / "print.png")))
            action.setToolTip("Druckplan ohne Rueckfrage ausfuehren")
            action.clicked.connect(lambda _checked=False, aggregate=item: self._on_open_product_print_clicked(aggregate))
        else:
            action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
            action.setToolTip("Druckplan/PDF fuer dieses Produkt einrichten")
            action.clicked.connect(lambda _checked=False, aggregate=item: self._on_open_product_manage_clicked(aggregate))
        layout.addWidget(action)
        return row

    @staticmethod
    def _open_product_description(item: PrintProductAggregate) -> str:
        desc_raw = str(item.description or "").strip()
        desc_parts = [part.strip() for part in desc_raw.split("|") if part.strip()]
        desc_parts = [part for part in desc_parts if "rabatt" not in part.casefold()]
        if desc_parts:
            text = " | ".join(desc_parts)
            return text if text.casefold().startswith("besetzung:") else f"Besetzung: {text}"
        category = str(getattr(item, "category_label", "") or "").strip()
        return f"Besetzung: {category}" if category else "Besetzung: unbekannt"

    def _plain_open_print_product_line(self, item: PrintProductAggregate) -> str:
        return (
            f"{max(1, int(item.quantity or 1))}x "
            f"{str(item.title or item.sku or 'Unbenanntes Produkt').strip()} "
            f"{str(item.sku or '-').strip()} "
            f"{self._open_product_description(item)}"
        )

    def _open_print_product_ready(self, item: PrintProductAggregate) -> bool:
        try:
            catalog: ProductCatalogService = self._container.resolve(ProductCatalogService)
            config = catalog.resolve_print_config(item.sku, title=item.title)
        except Exception as exc:  # noqa: BLE001 - invalid config should show settings.
            logger.debug("Open print product config lookup failed sku=%s: %s", item.sku, exc)
            return False
        path = str(config.get("path") or "").strip()
        plan = config.get("print_plan")
        profile_id = str(config.get("profile_id") or "").strip()
        if not path or not Path(path).exists():
            return False
        return bool(profile_id or (isinstance(plan, list) and any(isinstance(entry, dict) for entry in plan)))

    def _piece_block_from_open_product(self, item: PrintProductAggregate) -> PieceBlock:
        sku = str(item.sku or "").strip().upper()
        title = str(item.title or "").strip() or sku
        description = str(item.description or "").strip()
        product: Product | None = None
        config: dict[str, object] = {}
        try:
            catalog: ProductCatalogService = self._container.resolve(ProductCatalogService)
            product = catalog.resolve_sku(sku)
            config = catalog.resolve_print_config(sku, title=title)
        except Exception as exc:  # noqa: BLE001 - dialog can still create config.
            logger.debug("Open print product catalog lookup failed sku=%s: %s", sku, exc)
        path = str(config.get("path") or "").strip()
        if product is None and path:
            product = Product(id=f"settings::{sku}", sku=sku, name=title, print_file_path=path)
        elif product is not None and path and not product.print_file_path.strip():
            product.print_file_path = path
        return PieceBlock(
            sku=sku,
            name=title,
            qty_needed=max(1, int(item.quantity or 1)),
            note=description,
            is_unreleased=True,
            print_profile_id=str(config.get("profile_id") or "").strip(),
            print_plan=[
                entry for entry in (config.get("print_plan") or [])
                if isinstance(entry, dict)
            ],
            product=product,
            stock_status=None,
        )

    def _on_open_product_manage_clicked(self, item: PrintProductAggregate) -> None:
        from xw_office.ui.modules.rechnungen.print_dialog import _configure_missing_piece_print

        block = self._piece_block_from_open_product(item)
        signals: AppSignals = self._container.resolve(AppSignals)
        if _configure_missing_piece_print(self, self._container, block):
            signals.status_message.emit(f"Druckkonfiguration fuer {block.sku} gespeichert.", 5000)
        else:
            signals.status_message.emit(
                f"Druckkonfiguration fuer {block.sku} nicht geaendert.",
                5000,
            )
        self._refresh_open_invoice_overview()

    def _on_open_product_print_clicked(self, item: PrintProductAggregate) -> None:
        self._on_product_print_clicked(
            self._piece_block_from_open_product(item),
            max(1, int(item.quantity or 1)),
        )

    @staticmethod
    def _format_open_print_products(overview: OpenInvoiceOverview) -> str:
        style = (
            "<style>"
            "body { color: #e2e8f0; font-family: 'Segoe UI', sans-serif; font-size: 12px; }"
            "table { width: 100%; border-collapse: collapse; }"
            "td { vertical-align: top; padding: 3px 0; }"
            "td.qty { width: 56px; color: #e2e8f0; font-weight: 600; white-space: nowrap; }"
            "td.main { padding-right: 10px; }"
            "td.sku { width: 110px; color: #93c5fd; white-space: nowrap; text-align: right; }"
            "div.title { font-weight: 700; color: #ffffff; }"
            "div.desc { margin-top: 1px; color: #cbd5e1; font-size: 11px; }"
            "div.msg { color: #cbd5e1; }"
            "</style>"
        )
        if overview.unknown and not overview.print_products:
            return f"{style}<div class='msg'>Print-Produkte werden ermittelt...</div>"
        if not overview.print_products:
            return f"{style}<div class='msg'>Keine physischen Print-Produkte in den offenen Rechnungen gefunden.</div>"
        rows: list[str] = []
        for item in overview.print_products:
            title_raw = str(item.title or "").strip() or str(item.sku or "").strip() or "Unbenanntes Produkt"
            desc_raw = RechnungenView._open_product_description(item)
            sku_raw = str(item.sku or "").strip() or "-"
            rows.append(
                "<tr>"
                f"<td class='qty'>{max(1, int(item.quantity))}x</td>"
                "<td class='main'>"
                f"<div class='title'>{html.escape(title_raw)}</div>"
                f"<div class='desc'>{html.escape(desc_raw)}</div>"
                "</td>"
                f"<td class='sku'>{html.escape(sku_raw)}</td>"
                "</tr>"
            )
        if overview.unknown:
            rows.append("<tr><td colspan='3'><div class='desc'>Weitere Print-Produkte werden noch ermittelt.</div></td></tr>")
        return f"{style}<table>{''.join(rows)}</table>"

    def _warm_wix_context_for_summaries(self, summaries: list[InvoiceSummary]) -> None:
        """Prefetch full Wix contexts without delaying the invoice list.

        Visible rows are warmed in bounded batches so row-to-row selection in
        the right-hand panel is fast without flooding the Wix API.
        """
        if self._shutting_down:
            return
        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        added = 0
        prioritized = self._prioritize_summaries_for_background_prefetch(summaries)
        for summary in prioritized[:_WIX_WARM_QUEUE_LIMIT]:
            ref = str(summary.order_reference or "").strip()
            if not ref or ref in self._wix_warm_queue or ref in self._wix_warm_inflight_refs:
                continue
            if (
                self._get_cached_wix_context(ref) is not None
                and service.get_cached_invoice_list_hints(ref) is not None
            ):
                continue
            self._wix_warm_queue.append(ref)
            added += 1
            if len(self._wix_warm_queue) >= _WIX_WARM_QUEUE_LIMIT:
                break
        if added:
            logger.info(
                "Wix context warmup queued refs=%s pending=%s",
                added,
                len(self._wix_warm_queue),
            )
        self._start_next_wix_warm_batch()

    def _start_next_wix_warm_batch(self) -> None:
        if self._shutting_down:
            return
        if not self._can_run_wix_warm_job():
            return
        refs = self._wix_warm_queue[:_WIX_WARM_BATCH_SIZE]
        if not refs:
            return
        del self._wix_warm_queue[:_WIX_WARM_BATCH_SIZE]
        self._wix_warm_inflight_refs = set(refs)
        self._wix_warm_started_at = time.perf_counter()
        logger.info("Wix context warmup start refs=%s pending=%s", len(refs), len(self._wix_warm_queue))
        handle = self._background_jobs.submit_callable(
            queue="network-background",
            priority=_PRIORITY_WIX_WARMUP,
            key="wix-warmup",
            fn=lambda token, batch=tuple(refs): self._run_wix_warm_batch(batch, token),
            on_result=self._on_wix_warm_result,
            on_error=self._on_wix_warm_error,
            on_finished=self._on_wix_warm_finished,
            owner=self,
            replace="coalesce_pending",
            can_start=self._can_run_wix_warm_job,
        )
        self._wix_warm_handle = handle
        self._wix_warm_worker = handle.worker

    def _can_run_wix_warm_job(self) -> bool:
        if self._shutting_down:
            return False
        if self._wix_warm_worker is not None and self._wix_warm_worker.isRunning():
            return False
        if self._wix_context_worker is not None and self._wix_context_worker.isRunning():
            return False
        if self._invoice_detail_worker is not None and self._invoice_detail_worker.isRunning():
            return False
        return True

    def _run_wix_warm_batch(self, refs: tuple[str, ...], token: CancelToken) -> list[dict[str, object]]:
        token.raise_if_cancelled()
        wix_client: WixOrdersClient = self._container.resolve(WixOrdersClient)
        if not wix_client.has_credentials():
            return [
                {
                    "reference": ref,
                    "status": "Kein Wix-API-Key konfiguriert.",
                    "meta": {},
                    "items": [],
                    "patch": self._blank_hint_patch(),
                }
                for ref in refs
            ]

        engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
        invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        rows: list[dict[str, object]] = []
        for ref in refs:
            token.raise_if_cancelled()
            try:
                # All three operations share WixOrdersClient's persistent
                # read-through cache, so only the first one can hit Wix.
                meta = self._resolve_wix_order_summary(wix_client, ref, token)
                token.raise_if_cancelled()
                wix_items = self._fetch_wix_order_line_items(wix_client, ref, token)
                token.raise_if_cancelled()
                pieces = engine.get_piece_blocks(wix_items, invoice_ref=ref)
                token.raise_if_cancelled()
                hints = invoice_service.resolve_invoice_list_hints(ref)
                rows.append(
                    {
                        "reference": ref,
                        "status": "" if meta else "Wix-Order nicht gefunden",
                        "meta": meta if isinstance(meta, dict) else {},
                        "items": pieces,
                        "patch": hints.as_row_patch(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - warmup must not affect the list.
                if token.cancelled:
                    raise
                logger.warning("Wix warmup failed ref=%s: %s", ref, exc)
                rows.append(
                    {
                        "reference": ref,
                        "status": f"Wix-Fehler: {exc}",
                        "meta": {},
                        "items": [],
                        "patch": self._blank_hint_patch(),
                    }
                )
        return rows

    def _on_wix_warm_result(self, payload: object) -> None:
        if self._shutting_down:
            return
        rows = payload if isinstance(payload, list) else []
        elapsed_ms = int((time.perf_counter() - self._wix_warm_started_at) * 1000) if self._wix_warm_started_at else 0
        logger.info("Wix context warmup result refs=%s elapsed_ms=%s", len(rows), elapsed_ms)
        selected = self._selected_summary()
        selected_ref = selected.order_reference.strip() if selected is not None else ""
        for row in rows:
            data = row if isinstance(row, dict) else {}
            ref = str(data.get("reference") or "").strip()
            if not ref:
                continue
            status = str(data.get("status") or "").strip()
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            items = data.get("items") if isinstance(data.get("items"), list) else []
            patch = data.get("patch") if isinstance(data.get("patch"), dict) else self._blank_hint_patch()
            self._put_cached_wix_context(ref, status=status, meta=meta, items=items)
            self._apply_hint_patch_to_visible_rows(ref, patch)
            if ref == selected_ref and not status:
                self._on_wix_meta_loaded({**meta, "__requested_ref": ref})
                self._on_stuecke_loaded({"__requested_ref": ref, "items": items})

    def _on_wix_warm_error(self, exc: Exception) -> None:
        logger.warning("Wix context warmup failed: %s", exc)

    def _on_wix_warm_finished(self) -> None:
        self._wix_warm_worker = None
        self._wix_warm_handle = None
        self._wix_warm_inflight_refs.clear()
        if self._shutting_down:
            return
        self._start_next_wix_warm_batch()

    def _restart_hint_prefetch(self) -> None:
        self._hint_seq += 1
        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        draft_refs: list[str] = []
        seen: set[str] = set()
        for summary in self._prioritize_summaries_for_background_prefetch(self._summaries):
            ref = str(summary.order_reference or "").strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            if ref in self._wix_warm_queue or ref in self._wix_warm_inflight_refs:
                continue
            if service.get_cached_invoice_list_hints(ref) is not None:
                continue
            if summary.status_code == 100:
                draft_refs.append(ref)
        self._hint_draft_queue = draft_refs
        # Historical rows receive hints on selection. Their speculative
        # background loading previously consumed several minutes after startup.
        self._hint_rest_queue = []
        self._hint_inflight_ref = ""
        self._start_next_hint_prefetch()

    def _prioritize_summaries_for_background_prefetch(
        self,
        summaries: list[InvoiceSummary],
    ) -> list[InvoiceSummary]:
        if not summaries:
            return []

        ordered_rows: list[int] = []
        seen_rows: set[int] = set()

        selected_row = self._table.selected_source_row()
        if selected_row is not None and 0 <= selected_row < len(summaries):
            ordered_rows.append(selected_row)
            seen_rows.add(selected_row)
            for delta in (1, -1, 2, -2):
                neighbor = selected_row + delta
                if 0 <= neighbor < len(summaries) and neighbor not in seen_rows:
                    ordered_rows.append(neighbor)
                    seen_rows.add(neighbor)

        for row in self._table.visible_source_rows(limit=_WIX_WARM_QUEUE_LIMIT):
            if 0 <= row < len(summaries) and row not in seen_rows:
                ordered_rows.append(row)
                seen_rows.add(row)

        for row, _summary in enumerate(summaries):
            if row not in seen_rows:
                ordered_rows.append(row)

        return [summaries[row] for row in ordered_rows if 0 <= row < len(summaries)]

    def _prioritize_hint_prefetch_for_summary(self, summary: InvoiceSummary) -> None:
        ref = str(summary.order_reference or "").strip()
        if (
            not ref
            or summary.status_code == 100
            or self._hint_draft_queue
            or ref in self._wix_warm_queue
            or ref in self._wix_warm_inflight_refs
        ):
            return
        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        if service.get_cached_invoice_list_hints(ref) is not None or ref == self._hint_inflight_ref:
            return
        if ref in self._hint_rest_queue:
            self._hint_rest_queue.remove(ref)
        self._hint_rest_queue.insert(0, ref)
        self._start_next_hint_prefetch()

    def _start_next_hint_prefetch(self) -> None:
        self._submit_side_job(
            coalesce_key="hint-prefetch",
            priority=_PRIORITY_HINT_PREFETCH,
            start_fn=self._create_next_hint_prefetch_worker,
        )

    def _create_next_hint_prefetch_worker(self) -> BackgroundWorker | None:
        if self._hint_worker is not None and self._hint_worker.isRunning():
            return None
        ref = ""
        if self._hint_draft_queue:
            ref = self._hint_draft_queue.pop(0)
        elif self._hint_rest_queue:
            ref = self._hint_rest_queue.pop(0)
        if not ref:
            self._hint_inflight_ref = ""
            return None
        seq = self._hint_seq
        self._hint_inflight_ref = ref

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            hints = service.resolve_invoice_list_hints(ref)
            return {
                "seq": seq,
                "reference": ref,
                "patch": hints.as_row_patch(),
            }

        self._hint_worker = BackgroundWorker(job)
        self._hint_worker.signals.result.connect(self._on_hint_prefetch_result)
        self._hint_worker.signals.error.connect(self._on_hint_prefetch_error)
        self._hint_worker.signals.finished.connect(self._on_hint_prefetch_finished)
        return self._hint_worker

    def _on_hint_prefetch_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        seq = int(data.get("seq") or 0)
        if seq != self._hint_seq:
            return
        ref = str(data.get("reference") or "").strip()
        patch = data.get("patch") if isinstance(data.get("patch"), dict) else self._blank_hint_patch()
        self._apply_hint_patch_to_visible_rows(ref, patch)

    def _on_hint_prefetch_error(self, exc: Exception) -> None:
        logger.warning("Invoice hint prefetch failed: %s", exc)

    def _on_hint_prefetch_finished(self) -> None:
        self._hint_worker = None
        self._hint_inflight_ref = ""
        self._start_next_hint_prefetch()

    def _apply_hint_patch_to_visible_rows(self, reference: str, patch: dict[str, object]) -> None:
        ref = str(reference or "").strip()
        if not ref:
            return
        normalized_patch = dict(self._blank_hint_patch())
        normalized_patch.update(patch or {})
        for row_index, summary in enumerate(self._summaries):
            if str(summary.order_reference or "").strip() != ref:
                continue
            self._table.update_source_row_data(row_index, normalized_patch)

    def _set_detail_actions_busy(self, message: str) -> None:
        self._overlay.show_with_message(message)
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()
        for button in (
            self._btn_print,
            self._btn_print_plc,
            self._btn_print_music,
            self._btn_print_label,
            self._btn_open_plc_label,
            self._btn_send_invoice,
        ):
            button.setEnabled(False)

    def _clear_detail_actions_busy(self) -> None:
        self._overlay.hide()
        self._update_plc_controls()

    def _apply_fulfillment_flags_to_row(self, invoice_id: str, flags: object) -> None:
        if not isinstance(flags, dict):
            return
        target_id = str(invoice_id or "").strip()
        if not target_id:
            return
        for row_index, summary in enumerate(self._summaries):
            if str(summary.id or "").strip() != target_id:
                continue
            self._table.update_source_row_data(
                row_index,
                {
                    "FULFILLMENT": "",
                    "__fulfillment__": dict(flags),
                    "__tooltip__FULFILLMENT": "Label | Rechnung | Produkt | Mail | Wix | Zahlung",
                    "__align__FULFILLMENT": "center",
                },
            )
            selected = self._selected_summary()
            if selected is not None and str(selected.id or "").strip() == target_id:
                self._update_action_state()
            return

    def _on_print_clicked(self) -> None:
        if not self._print_allowed:
            return
        summary = self._require_selected_invoice()
        if summary is None:
            return
        if self._fulfillment_step_worker is not None and self._fulfillment_step_worker.isRunning():
            return

        self._set_detail_actions_busy("Rechnungsdruck laeuft...")

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            flags = service.print_invoice_for_invoice(summary.id)
            return {
                "invoice_id": summary.id,
                "invoice": summary.invoice_number or summary.id,
                "flags": flags.as_row_payload(),
            }

        self._fulfillment_step_worker = BackgroundWorker(job)
        self._fulfillment_step_worker.signals.result.connect(self._on_direct_invoice_print_result)
        self._fulfillment_step_worker.signals.error.connect(self._on_direct_invoice_print_error)
        self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)
        self._fulfillment_step_worker.start()

    def _on_print_label_clicked(self) -> None:
        if not self._print_allowed:
            return
        summary = self._require_selected_invoice()
        if summary is None:
            return
        shipping_lines = self._current_shipping_lines()
        if len(shipping_lines) < 2:
            QMessageBox.information(
                self,
                "Labeldruck",
                "Bitte zuerst eine vollständige Lieferadresse mit mindestens zwei Zeilen eingeben.",
            )
            return
        if self._fulfillment_step_worker is not None and self._fulfillment_step_worker.isRunning():
            return

        self._set_detail_actions_busy("Labeldruck laeuft...")

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            flags = service.print_label_for_invoice(summary.id, override_lines=shipping_lines)
            return {
                "invoice_id": summary.id,
                "invoice": summary.invoice_number or summary.id,
                "flags": flags.as_row_payload(),
            }

        self._fulfillment_step_worker = BackgroundWorker(job)
        self._fulfillment_step_worker.signals.result.connect(self._on_direct_label_print_result)
        self._fulfillment_step_worker.signals.error.connect(self._on_direct_label_print_error)
        self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)
        self._fulfillment_step_worker.start()

    def _on_custom_label_clicked(self) -> None:
        initial_lines = self._current_shipping_lines()
        if not initial_lines:
            selected = self._selected_summary()
            if selected is not None:
                initial_lines = list(self._shipping_address_overrides.get(selected.id, []))
        dlg = _CustomLabelDialog(self._container, initial_lines=initial_lines, parent=self)
        if not self._print_allowed:
            dlg._status.setText("Druckerstatus ist derzeit nicht bestaetigt. Druckversuch ist trotzdem moeglich.")  # noqa: SLF001
        dlg.exec()

    def _on_manual_plc_label_clicked(self) -> None:
        PlcLabelPrintDialog(self._container, None, self).exec()

    def _on_plc_statistics_clicked(self) -> None:
        PlcStatisticsDialog(self._container.resolve(PlcStatisticsService), self).exec()

    def _on_print_plc_selected(self) -> None:
        if not self._print_allowed:
            return
        summary = self._require_selected_invoice()
        if summary is None:
            return
        self._run_plc_print(summary)

    def _run_plc_print(self, summary: InvoiceSummary) -> None:
        if not self._print_allowed:
            return
        from xw_office.ui.modules.rechnungen.print_dialog import run_plc_label_pdf_print

        run_plc_label_pdf_print(
            self,
            self._container,
            invoice_number=summary.invoice_number,
        )
        self._last_plc_invoice = summary.invoice_number or summary.id
        self._plc_last.setText(f"Letzter PLC-Druck: {self._last_plc_invoice}")

    def _cached_customer_email_for_summary(self, summary: InvoiceSummary) -> str:
        """Resolve the customer's email from already-fetched Wix data (no fresh API call)."""
        ref = str(summary.order_reference or "").strip()
        if not ref:
            return ""
        cached_ctx = self._wix_context_cache.get(ref)
        if isinstance(cached_ctx, dict):
            meta = cached_ctx.get("meta")
            if isinstance(meta, dict):
                email = str(meta.get("wix_customer_email") or "").strip()
                if email:
                    return email
        try:
            wix_client: WixOrdersClient = self._container.resolve(WixOrdersClient)
            meta = wix_client.get_cached_order_summary(ref)
        except Exception as exc:  # noqa: BLE001 - cache lookup must never block the PLC popup.
            logger.debug("Cached Wix customer-email lookup failed ref=%s: %s", ref, exc)
            return ""
        if isinstance(meta, dict):
            return str(meta.get("wix_customer_email") or "").strip()
        return ""

    def _open_plc_post_popup(self, summary: InvoiceSummary) -> None:
        existing_label_path = self._resolve_plc_archive_path_for_summary(summary)
        if existing_label_path:
            box = QMessageBox(self)
            box.setWindowTitle("PLC-Label vorhanden")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("Für diese Rechnung existiert bereits ein PLC-Label.")
            box.setInformativeText(
                "Archiviertes Label öffnen oder neues Label mit Suffix -2 erstellen?\n\n"
                f"Archiv: {existing_label_path}"
            )
            open_btn = box.addButton("Archiv-PDF öffnen", QMessageBox.ButtonRole.AcceptRole)
            new_btn = box.addButton("Neues Label erstellen", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(open_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(existing_label_path))
                return
            if clicked is not new_btn:
                return

        selected = self._selected_summary()
        if selected is not None and selected.id == summary.id:
            address_lines = self._current_shipping_lines()
        else:
            address_lines = list(self._shipping_address_overrides.get(summary.id, []))
        recipient_email = self._cached_customer_email_for_summary(summary)
        dlg = PlcLabelPrintDialog(
            self._container,
            summary,
            self,
            address_override_lines=address_lines,
            recipient_email=recipient_email,
        )
        dlg.exec()
        self._plc_archive_lookup_cache.pop(
            (
                str(summary.order_reference or "").strip(),
                str(summary.invoice_number or summary.id or "").strip(),
            ),
            None,
        )

    def _on_print_music_clicked(self) -> None:
        if not self._print_allowed:
            return
        if self._require_selected_invoice() is None:
            return
        if self._product_print_worker is not None and self._product_print_worker.isRunning():
            return
        from xw_office.ui.modules.rechnungen.print_dialog import prepare_piece_pdf_print

        selected_jobs: list[tuple[PieceBlock, int, Callable[[], None]]] = []
        skipped: list[str] = []
        for block, qty, flagged in self._piece_model.rows():
            if not flagged:
                continue
            qty = max(1, int(qty or self._default_piece_print_qty(block)))
            if not block.has_direct_print_config:
                skipped.append(block.sku)
                continue
            job = prepare_piece_pdf_print(self, self._container, piece=block, copies=qty)
            if job is None:
                skipped.append(block.sku)
                continue
            selected_jobs.append((block, qty, job))

        if not selected_jobs:
            message = "Keine druckfaehigen Produkte fuer diese Rechnung gefunden."
            if skipped:
                message += "\n\nOhne vollstaendige Druckkonfiguration:\n" + ", ".join(skipped)
            QMessageBox.information(self, "Noten drucken", message)
            return

        row = self._table.selected_source_row()
        invoice_ref = ""
        if row is not None and 0 <= row < len(self._summaries):
            invoice_ref = self._summaries[row].invoice_number or self._summaries[row].id

        self._set_piece_print_controls_enabled(False)
        self._btn_print_music.setEnabled(False)
        signals: AppSignals = self._container.resolve(AppSignals)
        total_copies = sum(qty for _block, qty, _job in selected_jobs)
        signals.status_message.emit(
            f"Notendruck fuer {len(selected_jobs)} Produkt(e) gestartet ({total_copies}x).",
            5000,
        )

        def worker_job() -> dict[str, object]:
            warnings: list[str] = []
            printed: list[str] = []
            for block, qty, job in selected_jobs:
                job()
                printed.append(f"{block.sku} ({qty}x)")
                try:
                    engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
                    engine.record_print_and_update_sevdesk(block, qty, invoice_ref=invoice_ref)
                except Exception as exc:
                    logger.warning("Stock update after batch product print failed: %s", exc)
                    warnings.append(f"{block.sku}: {exc}")
            return {
                "sku": f"{len(printed)} Produkt(e)",
                "quantity": total_copies,
                "stock_warning": "\n".join(warnings),
                "printed": ", ".join(printed),
                "skipped": ", ".join(skipped),
            }

        self._product_print_worker = BackgroundWorker(worker_job)
        self._product_print_worker.signals.result.connect(self._on_product_print_result)
        self._product_print_worker.signals.error.connect(self._on_product_print_error)
        self._product_print_worker.signals.finished.connect(self._on_product_print_finished)
        self._product_print_worker.start()

    def _on_send_invoice_clicked(self) -> None:
        summary = self._require_selected_invoice()
        if summary is None:
            return
        if self._invoice_mail_worker is not None and self._invoice_mail_worker.isRunning():
            return

        self._set_detail_actions_busy("Rechnungsmail wird gesendet...")

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            flags, recipient, subject = service.send_invoice_mail_for_invoice(summary)
            return {
                "invoice_id": summary.id,
                "invoice": summary.invoice_number or summary.id,
                "recipient": recipient,
                "subject": subject,
                "flags": flags.as_row_payload(),
            }

        self._invoice_mail_worker = BackgroundWorker(job)
        self._invoice_mail_worker.signals.result.connect(self._on_send_invoice_result)
        self._invoice_mail_worker.signals.error.connect(self._on_send_invoice_error)
        self._invoice_mail_worker.signals.finished.connect(self._on_send_invoice_finished)
        self._invoice_mail_worker.start()

    def _on_table_selection_changed(
        self,
        _selected: Any,
        _deselected: Any,
    ) -> None:
        self._refresh_detail_for_selection()

    def _on_table_clicked(self, index: Any) -> None:
        row = int(index.row()) if hasattr(index, "row") else -1
        if row < 0:
            return
        self._select_visible_table_row(row)

    def _select_visible_table_row(self, row: int) -> None:
        if row < 0:
            return
        selection_model = self._table.selectionModel()
        selected_before = (
            [(int(index.row()), int(index.column())) for index in selection_model.selectedRows()]
            if selection_model is not None
            else []
        )
        self._table.selectRow(row)
        model = self._table.model()
        if model is not None:
            index = model.index(row, 0)
            if index.isValid():
                self._table.setCurrentIndex(index)
        self._table.viewport().update()
        selected_after = (
            [(int(index.row()), int(index.column())) for index in selection_model.selectedRows()]
            if selection_model is not None
            else []
        )
        if selected_after == selected_before:
            self._refresh_detail_for_selection()

    def eventFilter(self, watched: Any, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self._table.viewport() and event.type() in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Leave,
        ):
            if event.type() == QEvent.Type.Leave:
                self._table.viewport().unsetCursor()
                return super().eventFilter(watched, event)
            if isinstance(event, QMouseEvent):
                index = self._table.indexAt(event.position().toPoint())
                if index.isValid():
                    if event.type() == QEvent.Type.MouseButtonPress:
                        multi_select_modifier = event.modifiers() & (
                            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                        )
                        if (
                            event.button() == Qt.MouseButton.LeftButton
                            and not multi_select_modifier
                        ):
                            self._select_visible_table_row(int(index.row()))
                        return super().eventFilter(watched, event)
                    actions_col = _TABLE_COLUMNS.index("AKTIONEN")
                    sevdesk_col = _TABLE_COLUMNS.index("sevDesk")
                    if event.type() == QEvent.Type.MouseMove:
                        if int(index.column()) == sevdesk_col:
                            rect = self._table.visualRect(index)
                            row_data = index.data(Qt.ItemDataRole.UserRole)
                            can_remove = bool(isinstance(row_data, dict) and row_data.get("__draft_remove_enabled__"))
                            hovered_remove = can_remove and self._sevdesk_delegate.hit_remove_action(
                                local_x=event.position().x() - rect.x(),
                                local_y=event.position().y() - rect.y(),
                                width=rect.width(),
                                height=rect.height(),
                            )
                            if hovered_remove:
                                self._table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                            else:
                                self._table.viewport().unsetCursor()
                        elif int(index.column()) == actions_col:
                            rect = self._table.visualRect(index)
                            action = self._actions_delegate.action_at_x(
                                local_x=event.position().x() - rect.x(),
                                width=rect.width(),
                                height=rect.height(),
                            )
                            if action:
                                self._table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                            else:
                                self._table.viewport().unsetCursor()
                        else:
                            self._table.viewport().unsetCursor()
                        return super().eventFilter(watched, event)

                    self._select_visible_table_row(int(index.row()))
                    if int(index.column()) == sevdesk_col:
                        rect = self._table.visualRect(index)
                        row_data = index.data(Qt.ItemDataRole.UserRole)
                        can_remove = bool(isinstance(row_data, dict) and row_data.get("__draft_remove_enabled__"))
                        if can_remove and self._sevdesk_delegate.hit_remove_action(
                            local_x=event.position().x() - rect.x(),
                            local_y=event.position().y() - rect.y(),
                            width=rect.width(),
                            height=rect.height(),
                        ):
                            source_index = self._table.model().mapToSource(index)
                            row = int(source_index.row())
                            if 0 <= row < len(self._summaries):
                                self._confirm_delete_draft(self._summaries[row])
                            return True
                    fulfillment_col = _TABLE_COLUMNS.index("FULFILLMENT")
                    if int(index.column()) == fulfillment_col:
                        rect = self._table.visualRect(index)
                        chip = self._fulfillment_delegate.chip_at_x(
                            local_x=event.position().x() - rect.x(),
                            width=rect.width(),
                            height=rect.height(),
                        )
                        if chip:
                            source_index = self._table.model().mapToSource(index)
                            row = int(source_index.row())
                            if 0 <= row < len(self._summaries):
                                row_payload = self._table.selected_row_data() or {}
                                flags = row_payload.get("__fulfillment__")
                                self._run_fulfillment_chip_action(self._summaries[row], chip, flags)
                    if int(index.column()) == actions_col:
                        rect = self._table.visualRect(index)
                        action = self._actions_delegate.action_at_x(
                            local_x=event.position().x() - rect.x(),
                            width=rect.width(),
                            height=rect.height(),
                        )
                        if action:
                            source_index = self._table.model().mapToSource(index)
                            row = int(source_index.row())
                            if 0 <= row < len(self._summaries):
                                self._run_row_action(self._summaries[row], action)
                else:
                    self._table.viewport().unsetCursor()
        return super().eventFilter(watched, event)

    def _run_fulfillment_chip_action(
        self,
        summary: InvoiceSummary,
        chip: str,
        flags: object,
    ) -> None:
        if self._fulfillment_step_worker is not None and self._fulfillment_step_worker.isRunning():
            return

        labels = {
            "label_printed": "Label",
            "invoice_printed": "Rechnung",
            "product_ready": "Produkt",
            "mail_sent": "Mail",
            "wix_fulfilled": "Wix",
            "payment_booked": "Zahlung",
        }
        self._set_detail_actions_busy(f"Retry {labels.get(chip, chip)} laeuft...")

        invoice_id = summary.id

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            updated = service.retry_fulfillment_step(invoice_id, chip)
            payload = updated.as_row_payload() if hasattr(updated, "as_row_payload") else {}
            return {
                "invoice_id": invoice_id,
                "invoice": summary.invoice_number or summary.id,
                "chip": chip,
                "flags": payload,
            }

        self._fulfillment_step_worker = BackgroundWorker(job)
        self._fulfillment_step_worker.signals.result.connect(self._on_fulfillment_step_result)
        self._fulfillment_step_worker.signals.error.connect(self._on_fulfillment_step_error)
        self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)
        self._fulfillment_step_worker.start()

    def _on_fulfillment_step_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice_id = str(data.get("invoice_id") or "").strip()
        invoice = str(data.get("invoice") or "—")
        chip = str(data.get("chip") or "")
        self._apply_fulfillment_flags_to_row(invoice_id, data.get("flags"))
        QMessageBox.information(
            self,
            "Fulfillment aktualisiert",
            f"Rechnung {invoice}: Schritt '{chip}' wurde erneut ausgeführt.",
        )

    def _on_fulfillment_step_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Fulfillment-Fehler",
            f"Schritt konnte nicht ausgeführt werden:\n\n{exc}",
        )

    def _on_fulfillment_step_finished(self) -> None:
        self._fulfillment_step_worker = None
        self._clear_detail_actions_busy()

    def _run_row_action(self, summary: InvoiceSummary, action: str) -> None:
        if action == "post":
            self._open_plc_post_popup(summary)
            return
        if action == "wix":
            self._open_wix_download_links(summary)
            return
        if action == "mail":
            self._open_customer_mail(summary)
            return

    def _confirm_delete_draft(self, summary: InvoiceSummary) -> None:
        if self._delete_draft_worker is not None and self._delete_draft_worker.isRunning():
            return
        if summary.status_code != _DRAFT_STATUS or str(summary.invoice_number or "").strip():
            return
        answer = QMessageBox.question(
            self,
            "Rechnungsentwurf löschen",
            "Rechnungsentwurf wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._overlay.show_with_message("Rechnungsentwurf wird gelöscht…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, str]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            service.delete_draft_invoice(summary.id)
            return {
                "label": str(summary.order_reference or summary.id or "").strip(),
            }

        self._delete_draft_worker = BackgroundWorker(job)
        self._delete_draft_worker.signals.result.connect(self._on_delete_draft_result)
        self._delete_draft_worker.signals.error.connect(self._on_delete_draft_error)
        self._delete_draft_worker.signals.finished.connect(self._on_delete_draft_finished)
        self._delete_draft_worker.start()

    def _on_delete_draft_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        label = str(data.get("label") or "Entwurf").strip() or "Entwurf"
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(f"Entwurf gelöscht: {label}", 5000)
        self._reload_first_page()

    def _on_delete_draft_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rechnungsentwurf löschen",
            f"Der Rechnungsentwurf konnte nicht gelöscht werden:\n\n{exc}",
        )

    def _on_delete_draft_finished(self) -> None:
        self._delete_draft_worker = None
        self._overlay.hide()

    def _resolve_plc_archive_path_for_summary(self, summary: InvoiceSummary) -> str:
        order_ref = str(summary.order_reference or "").strip()
        invoice_no = str(summary.invoice_number or summary.id or "").strip()
        if not order_ref or not invoice_no:
            return ""
        cache_key = (order_ref, invoice_no)
        cached = self._plc_archive_lookup_cache.get(cache_key)
        if cached is not None:
            return cached
        path = self._plc_label_archive.find_for_invoice(order_reference=order_ref, invoice_number=invoice_no)
        resolved = os.fspath(path) if path is not None else ""
        self._plc_archive_lookup_cache[cache_key] = resolved
        return resolved

    def _on_open_plc_label_clicked(self) -> None:
        path = str(self._selected_plc_label_path or "").strip()
        if not path:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.warning(self, "PLC-PDF öffnen", "Das PLC-Label konnte nicht geöffnet werden.")

    def _open_customer_mail(self, summary: InvoiceSummary) -> None:
        if self._customer_mail_worker is not None and self._customer_mail_worker.isRunning():
            QMessageBox.information(self, "Kunden-Mail", "Eine Kunden-Mail wird bereits vorbereitet.")
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Kunden-Mail wird vorbereitet…", 2500)
        email_hint = self._customer_email_from_loaded_context(summary)
        subject = self._customer_mail_subject(summary)

        def job() -> dict[str, str]:
            resolved_email = email_hint
            if not resolved_email:
                try:
                    service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
                    context = service.get_invoice_detail_context(summary)
                    resolved_email = self._clean_email_value(context.get("customer_email"))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Customer mail context load failed for invoice %s: %s", summary.id, exc)
            if not resolved_email and summary.order_reference.strip():
                try:
                    wix_orders: WixOrdersClient = self._container.resolve(WixOrdersClient)
                    meta = wix_orders.resolve_order_summary(summary.order_reference)
                    resolved_email = self._clean_email_value(meta.get("wix_customer_email"))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Customer mail Wix lookup failed for invoice %s: %s", summary.id, exc)
            outlook_opened = False
            if resolved_email:
                try:
                    outlook_opened = self._open_customer_mail_outlook(resolved_email, subject)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Outlook customer mail compose failed: %s", exc)
            return {
                "invoice_id": str(summary.id or "").strip(),
                "email": resolved_email,
                "subject": subject,
                "outlook_opened": "1" if outlook_opened else "",
            }

        self._customer_mail_worker = BackgroundWorker(job)
        self._customer_mail_worker.signals.result.connect(lambda payload: self._on_customer_mail_ready(summary, payload))
        self._customer_mail_worker.signals.error.connect(self._on_customer_mail_error)
        self._customer_mail_worker.signals.finished.connect(lambda: setattr(self, "_customer_mail_worker", None))
        self._customer_mail_worker.start()

    def _on_customer_mail_ready(self, summary: InvoiceSummary, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        email = self._clean_email_value(data.get("email"))
        if not email:
            QMessageBox.information(
                self,
                "Kunden-Mail",
                "Für diese Rechnung konnte keine Kunden-E-Mail-Adresse ermittelt werden.",
            )
            return
        if str(data.get("outlook_opened") or "").strip():
            signals: AppSignals = self._container.resolve(AppSignals)
            signals.status_message.emit("Kunden-Mail in Outlook geöffnet.", 3000)
            return
        subject = str(data.get("subject") or "").strip() or self._customer_mail_subject(summary)
        self._open_customer_mail_url(email, subject)

    def _on_customer_mail_error(self, exc: Exception) -> None:
        QMessageBox.warning(self, "Kunden-Mail", f"Mail konnte nicht vorbereitet werden:\n\n{exc}")

    def _open_customer_mail_url(self, email: str, subject: str) -> None:
        clean_email = self._clean_email_value(email)
        if not clean_email:
            QMessageBox.information(self, "Kunden-Mail", "Keine gültige Kunden-E-Mail-Adresse vorhanden.")
            return
        url = f"mailto:{quote(clean_email, safe='@._+-')}?subject={quote(subject, safe='')}"
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "Kunden-Mail", "Das Standard-Mailprogramm konnte nicht geöffnet werden.")

    def _open_customer_mail_outlook(self, email: str, subject: str) -> bool:
        sender_email = self._outlook_sender_email()
        if not sender_email:
            return False
        payload = json.dumps(
            {"to": email, "subject": subject, "sender": sender_email},
            ensure_ascii=False,
        )
        env = dict(os.environ)
        src_path = str(Path(__file__).resolve().parents[4])
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{src_path}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else src_path
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "xw_office.services.mailing.outlook_compose"],
                input=payload,
                text=True,
                capture_output=True,
                timeout=20,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Outlook compose timed out; falling back to mailto")
            return False
        if completed.returncode == 0:
            return True
        logger.warning(
            "Outlook compose subprocess failed rc=%s stderr=%s stdout=%s",
            completed.returncode,
            (completed.stderr or "").strip()[:500],
            (completed.stdout or "").strip()[:500],
        )
        return False

    def _outlook_sender_email(self) -> str:
        try:
            secrets: SecretService = self._container.resolve(SecretService)
            return self._clean_email_value(secrets.get_secret("OUTLOOK_SENDER_EMAIL"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("OUTLOOK_SENDER_EMAIL resolve failed: %s", exc)
            return ""

    @staticmethod
    def _customer_mail_subject(summary: InvoiceSummary) -> str:
        order_ref = str(summary.order_reference or "").strip() or "—"
        invoice_no = str(summary.invoice_number or "").strip() or str(summary.id or "").strip() or "—"
        return f"Best.-Nr. {order_ref} | {invoice_no}"

    def _customer_email_from_loaded_context(self, summary: InvoiceSummary) -> str:
        selected = self._selected_summary()
        if selected is not None and str(selected.id or "").strip() == str(summary.id or "").strip():
            email = self._clean_email_value(self._wix_customer_email.text())
            if email:
                return email
        if summary.order_reference.strip():
            cached = self._get_cached_wix_context(summary.order_reference)
            if cached is not None:
                meta = cached.get("meta") if isinstance(cached.get("meta"), dict) else {}
                email = self._clean_email_value(meta.get("wix_customer_email"))
                if email:
                    return email
        try:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            context = service.get_cached_invoice_detail_context(summary)
            if isinstance(context, dict):
                return self._clean_email_value(context.get("customer_email"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Customer mail cache lookup failed for invoice %s: %s", summary.id, exc)
        return ""

    @staticmethod
    def _clean_email_value(value: object) -> str:
        email = str(value or "").strip()
        if not email or email in {"—", "---", "-"}:
            return ""
        return email if "@" in email and "." in email.rsplit("@", 1)[-1] else ""

    def _open_wix_download_links(self, summary: InvoiceSummary) -> None:
        if not summary.order_reference.strip():
            QMessageBox.information(
                self,
                "Download-Links",
                "Diese Rechnung hat keine Wix-Order-Referenz.",
            )
            return
        wix_orders: WixOrdersClient = self._container.resolve(WixOrdersClient)
        url = wix_orders.resolve_order_dashboard_url(summary.order_reference)
        if not url:
            QMessageBox.warning(
                self,
                "Download-Links",
                "Wix-Order konnte nicht aufgelöst werden.",
            )
            return
        QDesktopServices.openUrl(QUrl(url))

    def _open_refund_dialog(self, summary: InvoiceSummary) -> None:
        dlg = RefundDialog(summary, self)
        if dlg.exec() != 1:
            return

        send_mail = dlg.send_customer_mail
        self._overlay.show_with_message("Rückerstattung wird ausgeführt…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, Any]:
            sevdesk_refund: SevDeskRefundClient = self._container.resolve(SevDeskRefundClient)
            wix_orders: WixOrdersClient = self._container.resolve(WixOrdersClient)

            cancel_payload = sevdesk_refund.cancel_invoice(summary.id)
            wix_payload: dict[str, Any] = {}
            wix_ok = False
            if summary.order_reference.strip():
                wix_payload = wix_orders.refund_full_order(
                    summary.order_reference,
                    send_customer_email=send_mail,
                    customer_reason=f"Storno {summary.invoice_number or summary.id}",
                )
                wix_ok = bool(wix_payload)
            return {
                "invoice": summary.invoice_number or summary.id,
                "cancel": cancel_payload,
                "wix": wix_payload,
                "wix_ok": wix_ok,
                "had_order_ref": bool(summary.order_reference.strip()),
            }

        self._refund_worker = BackgroundWorker(job)
        self._refund_worker.signals.result.connect(self._on_refund_result)
        self._refund_worker.signals.error.connect(self._on_refund_error)
        self._refund_worker.signals.finished.connect(self._on_refund_finished)
        self._refund_worker.start()

    def _on_refund_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice = str(data.get("invoice") or "—")
        had_order_ref = bool(data.get("had_order_ref"))
        wix_ok = bool(data.get("wix_ok"))

        if not had_order_ref:
            QMessageBox.information(
                self,
                "Rückerstattung durchgeführt",
                f"Rechnung {invoice}: sevDesk-Stornorechnung wurde erstellt.\n"
                "Keine Wix-Order-Referenz vorhanden, daher kein Zahlungsrefund in Wix.",
            )
            self._reload_first_page()
            return

        if wix_ok:
            QMessageBox.information(
                self,
                "Rückerstattung durchgeführt",
                f"Rechnung {invoice}: sevDesk-Storno + Wix-Zahlungsrefund erfolgreich.",
            )
        else:
            QMessageBox.warning(
                self,
                "Teilweise abgeschlossen",
                f"Rechnung {invoice}: sevDesk-Storno erstellt, aber Wix-Zahlungsrefund konnte nicht bestätigt werden.",
            )
        self._reload_first_page()

    def _on_refund_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rückerstattung fehlgeschlagen",
            f"Die Rückerstattung konnte nicht ausgeführt werden:\n\n{exc}",
        )

    def _on_refund_finished(self) -> None:
        self._overlay.hide()

    def _refresh_detail_for_selection(self) -> None:
        summary = self._selected_summary()
        self._detail_context_seq += 1
        seq = self._detail_context_seq
        if summary is None:
            self._reset_detail()
            return
        self._populate_detail_for_summary(summary)
        QTimer.singleShot(0, lambda s=summary, token=seq: self._hydrate_detail_for_selection(s, token))

    def _populate_detail_for_summary(self, summary: InvoiceSummary) -> None:
        self._gb_open.hide()
        self._gb_open_products.hide()
        self._gb_info.show()
        self._gb_shipping.show()
        self._dl_number.setText(summary.invoice_number or "")
        self._dl_date.setText(summary.formatted_date)
        self._dl_status.setText(summary.status_label())
        self._dl_brutto.setText(summary.formatted_brutto)
        self._dl_contact.setText(summary.contact_name or "")
        self._dl_country.setText(summary.display_country or "")
        if summary.buyer_note.strip():
            self._dl_note.setText(summary.buyer_note)
            self._gb_note.show()
        else:
            self._dl_note.setText("")
            self._gb_note.hide()
        self._dl_order_ref.setText(summary.order_reference or "")
        self._reset_wix_meta("Lade Wix-Daten…")
        self._update_action_state()
        self._gb_actions.show()
        self._update_plc_controls()
        self._prioritize_hint_prefetch_for_summary(summary)

    def _hydrate_detail_for_selection(self, summary: InvoiceSummary, seq: int) -> None:
        selected = self._selected_summary()
        if (
            seq != self._detail_context_seq
            or selected is None
            or str(selected.id or "").strip() != str(summary.id or "").strip()
        ):
            return
        self._prefill_detail_from_invoice_async(summary)
        if summary.order_reference:
            has_cached_wix_context = self._apply_cached_wix_context(summary.order_reference)
            self._load_wix_context(
                summary.order_reference,
                show_loading=not has_cached_wix_context,
            )
        else:
            self._reset_wix_meta("Keine Wix-Order-Referenz")
            self._reset_stuecke()

    def _reset_detail(self) -> None:
        self._gb_open.show()
        self._gb_open_products.show()
        self._gb_info.hide()
        self._gb_shipping.hide()
        for lbl in (
            self._dl_number, self._dl_date, self._dl_status, self._dl_brutto,
            self._dl_contact, self._dl_country,
        ):
            lbl.setText("—")
        self._dl_note.setText("")
        self._gb_note.hide()
        self._dl_order_ref.setText("—")
        self._reset_wix_meta("—")
        self._action_state.setText("Keine Rechnung ausgewählt")
        self._action_state.setStyleSheet("color: #64748b;")
        self._gb_actions.hide()
        self._update_plc_controls()
        self._reset_stuecke()

    def _update_action_state(self) -> None:
        row_data = self._table.selected_row_data() or {}
        payload = row_data.get("__fulfillment__")
        flags = payload if isinstance(payload, dict) else {}
        last_error = str(flags.get("last_error") or "").strip()
        last_warning = str(flags.get("last_warning") or "").strip()
        if last_error:
            self._action_state.setText(f"Letzter Fulfillment-Fehler: {last_error}")
            self._action_state.setStyleSheet("color: #ef5350; font-weight: 600;")
            return
        if last_warning:
            self._action_state.setText(f"Wix-/Fulfillment-Hinweis: {last_warning}")
            self._action_state.setStyleSheet("color: #f59e0b; font-weight: 600;")
            return
        self._action_state.setText("Aktionen für die ausgewählte Rechnung verfügbar.")
        self._action_state.setStyleSheet("color: #64748b;")

    def _reset_wix_meta(self, text: str) -> None:
        self._pending_wix_reference = ""
        self._wix_order_no.setText(text)
        self._wix_customer.setText("—")
        self._wix_customer_email.setText("—")
        self._shipping_source_lines = []
        self._shipping_status.setText(text)
        self._set_shipping_editor_lines([])

    def _prefill_detail_from_invoice(self, summary: InvoiceSummary) -> None:
        self._wix_order_no.setText(summary.order_reference or "â€”")
        try:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            context = service.get_invoice_detail_context(summary)
        except Exception as exc:
            logger.warning("Invoice detail prefill failed for %s: %s", summary.id, exc)
            self._wix_customer.setText(summary.contact_name or "â€”")
            if summary.order_reference:
                self._shipping_status.setText("Lade Wix-Datenâ€¦")
            else:
                self._shipping_status.setText("Keine Versandadresse verfuegbar")
            return

        customer_name = str(context.get("customer_name") or "").strip() or summary.contact_name or "â€”"
        customer_email = str(context.get("customer_email") or "").strip() or "â€”"
        shipping_lines = self._normalize_shipping_lines(context.get("shipping_lines"))  # type: ignore[arg-type]
        self._wix_customer.setText(customer_name)
        self._wix_customer_email.setText(customer_email)
        self._shipping_source_lines = shipping_lines
        override_lines = list(self._shipping_address_overrides.get(summary.id, []))
        if shipping_lines:
            self._shipping_status.setText("Adresse aus sevDesk")
            self._set_shipping_editor_lines(override_lines or shipping_lines)
        elif summary.order_reference:
            self._shipping_status.setText("Lade Wix-Datenâ€¦")
            self._set_shipping_editor_lines(override_lines)
        else:
            self._shipping_status.setText("Keine Versandadresse in sevDesk")
            self._set_shipping_editor_lines(override_lines)

    def _prefill_detail_from_invoice_async(self, summary: InvoiceSummary) -> None:
        override_lines = list(self._shipping_address_overrides.get(summary.id, []))
        current_lines = self._current_shipping_lines()
        if not current_lines:
            self._wix_order_no.setText(summary.order_reference or "---")
            self._wix_customer.setText(summary.contact_name or "---")
            self._wix_customer_email.setText("---")
            if summary.order_reference:
                self._shipping_status.setText("Lade Wix-Daten...")
            else:
                self._shipping_status.setText("Keine Versandadresse verfuegbar")
            self._set_shipping_editor_lines(override_lines)
        try:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invoice detail service unavailable for %s: %s", summary.id, exc)
            return

        try:
            context = service.get_cached_invoice_detail_context(summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invoice detail cache read failed for %s: %s", summary.id, exc)
            context = None
        if context is not None:
            self._apply_invoice_detail_context(summary.id, summary, context)
            return
        self._load_invoice_detail_context(summary)

    def _load_invoice_detail_context(self, summary: InvoiceSummary) -> None:
        invoice_id = str(summary.id or "").strip()
        if not invoice_id:
            return
        if self._invoice_detail_worker is not None and self._invoice_detail_worker.isRunning():
            self._queued_invoice_detail_id = invoice_id
            return

        self._invoice_detail_started_at = time.perf_counter()
        logger.debug("Rechnungen phase=selected-detail-load start invoice_id=%s", invoice_id)

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            context = service.get_invoice_detail_context(summary)
            return {"__invoice_id": invoice_id, "summary": summary, "context": context}

        self._invoice_detail_worker = BackgroundWorker(job)
        self._invoice_detail_worker.signals.result.connect(self._on_invoice_detail_context_loaded)
        self._invoice_detail_worker.signals.error.connect(self._on_invoice_detail_context_error)
        self._invoice_detail_worker.signals.finished.connect(self._on_invoice_detail_context_finished)
        self._invoice_detail_worker.start()

    def _on_invoice_detail_context_loaded(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice_id = str(data.get("__invoice_id") or "").strip()
        selected = self._selected_summary()
        if selected is None or invoice_id != str(selected.id or "").strip():
            return
        summary = data.get("summary")
        if not isinstance(summary, InvoiceSummary):
            summary = selected
        context = data.get("context") if isinstance(data.get("context"), dict) else {}
        self._apply_invoice_detail_context(invoice_id, summary, context)

    def _on_invoice_detail_context_error(self, exc: Exception) -> None:
        logger.warning("Invoice detail background load failed: %s", exc)

    def _on_invoice_detail_context_finished(self) -> None:
        if self._invoice_detail_started_at:
            elapsed_ms = int((time.perf_counter() - self._invoice_detail_started_at) * 1000)
            logger.debug("Rechnungen phase=selected-detail-load finished elapsed_ms=%s", elapsed_ms)
            self._invoice_detail_started_at = 0.0
        self._invoice_detail_worker = None
        queued_id = self._queued_invoice_detail_id.strip()
        self._queued_invoice_detail_id = ""
        if not queued_id:
            self._start_next_wix_warm_batch()
            if self._pending_open_overview_rows:
                self._start_open_invoice_overview(list(self._pending_open_overview_rows))
            return
        selected = self._selected_summary()
        if selected is None or queued_id != str(selected.id or "").strip():
            self._start_next_wix_warm_batch()
            if self._pending_open_overview_rows:
                self._start_open_invoice_overview(list(self._pending_open_overview_rows))
            return
        self._load_invoice_detail_context(selected)

    def _apply_invoice_detail_context(
        self,
        invoice_id: str,
        summary: InvoiceSummary,
        context: dict[str, object],
    ) -> None:
        selected = self._selected_summary()
        if selected is None or str(selected.id or "").strip() != str(invoice_id or "").strip():
            return
        customer_name = str(context.get("customer_name") or "").strip() or summary.contact_name or "---"
        customer_email = str(context.get("customer_email") or "").strip() or "---"
        shipping_lines = self._normalize_shipping_lines(context.get("shipping_lines"))  # type: ignore[arg-type]
        current_customer = str(self._wix_customer.text() or "").strip()
        current_email = str(self._wix_customer_email.text() or "").strip()
        if not current_customer or current_customer in {"---", "â€”", "Ã¢â‚¬â€"}:
            self._wix_customer.setText(customer_name)
        if not current_email or current_email in {"---", "â€”", "Ã¢â‚¬â€"}:
            self._wix_customer_email.setText(customer_email)
        override_lines = list(self._shipping_address_overrides.get(summary.id, []))
        current_lines = self._current_shipping_lines()
        if shipping_lines and not current_lines:
            self._shipping_source_lines = shipping_lines
            self._shipping_status.setText("Adresse aus sevDesk")
            self._set_shipping_editor_lines(override_lines or shipping_lines)
        elif summary.order_reference:
            if not current_lines:
                self._shipping_status.setText("Lade Wix-Daten...")
                self._set_shipping_editor_lines(override_lines)
        elif not current_lines:
            self._shipping_status.setText("Keine Versandadresse in sevDesk")
            self._set_shipping_editor_lines(override_lines)

    def _apply_cached_wix_context(self, order_reference: str) -> bool:
        ref = str(order_reference or "").strip()
        if not ref:
            return False
        try:
            wix_client: WixOrdersClient = self._container.resolve(WixOrdersClient)
            meta = wix_client.get_cached_order_summary(ref)
            cached_items = wix_client.get_cached_order_line_items(ref)
        except Exception as exc:  # noqa: BLE001 - cache must never block row selection.
            logger.debug("Persistent Wix context cache lookup failed ref=%s: %s", ref, exc)
            return False
        if meta is None:
            return False
        if not meta:
            self._put_cached_wix_context(
                ref,
                status="Wix-Order nicht gefunden",
                meta={},
                items=[],
            )
            self._reset_wix_meta("Wix-Order nicht gefunden")
            self._reset_stuecke()
            self._stuecke_hint.setText("Wix-Order nicht gefunden")
            self._stuecke_hint.show()
            self._gb_stuecke.show()
            return True
        self._on_wix_meta_loaded({**meta, "__requested_ref": ref})
        if cached_items is None:
            return True
        pieces = self._piece_blocks_from_cached_wix_items(cached_items)
        self._put_cached_wix_context(ref, status="", meta=meta, items=pieces)
        self._on_stuecke_loaded({"__requested_ref": ref, "items": pieces})
        return True

    @staticmethod
    def _piece_blocks_from_cached_wix_items(items: object) -> list[PieceBlock]:
        if not isinstance(items, list):
            return []
        pieces: list[PieceBlock] = []
        for item in items:
            sku = str(getattr(item, "sku", "") or "").strip()
            name = str(getattr(item, "name", "") or "").strip() or sku
            if not sku and not name:
                continue
            try:
                qty = max(1, int(getattr(item, "qty", 1) or 1))
            except (TypeError, ValueError):
                qty = 1
            pieces.append(
                PieceBlock(
                    sku=sku,
                    name=name,
                    qty_needed=qty,
                    note=str(getattr(item, "note", "") or "").strip(),
                    is_unreleased=bool(getattr(item, "is_unreleased", False)),
                )
            )
        return pieces

    def _load_wix_context(self, order_reference: str, *, show_loading: bool = True) -> None:
        ref = order_reference.strip()
        if not ref:
            self._reset_wix_meta("Keine Wix-Order-Referenz")
            self._reset_stuecke()
            return

        cached = self._get_cached_wix_context(ref)
        if cached is not None:
            self._wix_context_seq += 1
            seq = self._wix_context_seq
            self._pending_wix_reference = ref
            self._pending_stuecke_reference = ref
            status = str(cached.get("status") or "").strip()
            if status:
                self._reset_wix_meta(status)
                self._reset_stuecke()
                self._stuecke_hint.setText(status)
                self._stuecke_hint.show()
                self._gb_stuecke.show()
                return
            meta = cached.get("meta") if isinstance(cached.get("meta"), dict) else {}
            items = cached.get("items") if isinstance(cached.get("items"), list) else []
            self._on_wix_meta_loaded({**meta, "__requested_ref": ref, "seq": seq})
            self._on_stuecke_loaded({"__requested_ref": ref, "items": items, "seq": seq})
            return

        # A selected row takes precedence over speculative background work.  A
        # queued reference can be loaded now instead of waiting for all earlier
        # warmup entries; the direct load will still populate both cache tiers.
        if ref in self._wix_warm_queue:
            self._wix_warm_queue.remove(ref)
            logger.debug("Wix context warmup reprioritized ref=%s", ref)

        if self._wix_context_worker is not None and self._wix_context_worker.isRunning():
            self._background_jobs.cancel_key("selected-wix-context")
        if self._wix_warm_handle is not None and self._wix_warm_handle.running:
            self._background_jobs.cancel_key("wix-warmup")

        self._wix_context_seq += 1
        seq = self._wix_context_seq
        self._selected_wix_started_at = time.perf_counter()
        logger.debug("Rechnungen phase=selected-wix-context start ref=%s", ref)
        if show_loading:
            self._reset_wix_meta("Lade Wix-Daten...")
        self._pending_wix_reference = ref
        self._pending_stuecke_reference = ref
        self._reset_stuecke()
        self._stuecke_hint.setText("Wird geladen…")
        self._gb_stuecke.show()

        def job(token: CancelToken) -> dict[str, object]:
            token.raise_if_cancelled()
            wix_client: WixOrdersClient = self._container.resolve(WixOrdersClient)
            if not wix_client.has_credentials():
                return {
                    "seq": seq,
                    "__requested_ref": ref,
                    "status": "Kein Wix-API-Key konfiguriert.",
                    "meta": {},
                    "items": [],
                }

            meta = self._resolve_wix_order_summary(wix_client, ref, token)
            token.raise_if_cancelled()
            wix_items = self._fetch_wix_order_line_items(wix_client, ref, token)
            token.raise_if_cancelled()
            engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
            pieces = engine.get_piece_blocks(wix_items, invoice_ref=ref)
            token.raise_if_cancelled()
            return {
                "seq": seq,
                "__requested_ref": ref,
                "status": "",
                "meta": meta,
                "items": pieces,
            }

        handle = self._background_jobs.submit_callable(
            queue="ui-critical-network",
            priority=0,
            key="selected-wix-context",
            fn=job,
            on_result=self._on_wix_context_loaded,
            on_error=self._on_wix_context_error,
            on_finished=self._on_wix_context_finished,
            owner=self,
            replace="cancel_previous",
        )
        self._wix_context_handle = handle
        self._wix_context_worker = handle.worker

    @staticmethod
    def _resolve_wix_order_summary(
        wix_client: WixOrdersClient,
        ref: str,
        token: CancelToken,
    ) -> dict[str, str]:
        try:
            return wix_client.resolve_order_summary(ref, cancel_token=token)
        except TypeError as exc:
            if "cancel_token" not in str(exc):
                raise
            token.raise_if_cancelled()
            return wix_client.resolve_order_summary(ref)

    @staticmethod
    def _fetch_wix_order_line_items(
        wix_client: WixOrdersClient,
        ref: str,
        token: CancelToken,
    ) -> list[Any]:
        try:
            return list(wix_client.fetch_order_line_items(ref, cancel_token=token))
        except TypeError as exc:
            if "cancel_token" not in str(exc):
                raise
            token.raise_if_cancelled()
            return list(wix_client.fetch_order_line_items(ref))

    def _on_wix_context_loaded(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        seq = int(data.get("seq") or 0)
        requested_ref = str(data.get("__requested_ref") or "").strip()
        status = str(data.get("status") or "").strip()
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        self._put_cached_wix_context(
            requested_ref,
            status=status,
            meta=meta if not status else {},
            items=items if not status else [],
        )
        if seq != self._wix_context_seq:
            return
        selected = self._selected_summary()
        current_ref = selected.order_reference.strip() if selected is not None else ""
        if requested_ref and requested_ref != current_ref:
            return

        if status:
            self._wix_order_no.setText(requested_ref or "â€”")
            if not self._current_shipping_lines():
                self._shipping_status.setText(status)
            self._reset_stuecke()
            self._stuecke_hint.setText(status)
            self._stuecke_hint.show()
            self._gb_stuecke.show()
            return

        self._on_wix_meta_loaded({**meta, "__requested_ref": requested_ref})
        self._on_stuecke_loaded({"__requested_ref": requested_ref, "items": items})

    def _on_wix_context_error(self, exc: Exception) -> None:
        if not self._current_shipping_lines():
            self._shipping_status.setText(f"Wix-Fehler: {exc}")
        self._reset_stuecke()
        self._stuecke_hint.setText(f"Fehler: {exc}")
        self._stuecke_hint.show()
        self._gb_stuecke.show()

    def _on_wix_context_finished(self) -> None:
        if self._selected_wix_started_at:
            elapsed_ms = int((time.perf_counter() - self._selected_wix_started_at) * 1000)
            logger.debug("Rechnungen phase=selected-wix-context finished elapsed_ms=%s", elapsed_ms)
            self._selected_wix_started_at = 0.0
        self._wix_context_worker = None
        queued_ref = self._queued_wix_context_ref.strip()
        self._queued_wix_context_ref = ""
        if not queued_ref:
            self._start_next_wix_warm_batch()
            if self._pending_open_overview_rows:
                self._start_open_invoice_overview(list(self._pending_open_overview_rows))
            return
        selected = self._selected_summary()
        current_ref = selected.order_reference.strip() if selected is not None else ""
        if not current_ref or queued_ref != current_ref:
            self._start_next_wix_warm_batch()
            if self._pending_open_overview_rows:
                self._start_open_invoice_overview(list(self._pending_open_overview_rows))
            return
        self._load_wix_context(queued_ref)

    @staticmethod
    def _load_phase_label(status_filter: int | None) -> str:
        if status_filter == _DRAFT_STATUS:
            return "draft-load"
        if status_filter is None:
            return "recent-non-draft-load"
        return f"status-{status_filter}-load"

    def _get_cached_wix_context(self, reference: str) -> dict[str, object] | None:
        ref = str(reference or "").strip()
        if not ref:
            return None
        cached = self._wix_context_cache.get(ref)
        if not cached:
            return None
        ts = float(cached.get("ts") or 0.0)
        if (time.monotonic() - ts) > _WIX_CONTEXT_CACHE_TTL_SECONDS:
            self._wix_context_cache.pop(ref, None)
            return None
        return cached

    def _put_cached_wix_context(
        self,
        reference: str,
        *,
        status: str,
        meta: dict[str, str],
        items: list[PieceBlock],
    ) -> None:
        ref = str(reference or "").strip()
        if not ref:
            return
        self._wix_context_cache[ref] = {
            "ts": time.monotonic(),
            "status": status,
            "meta": dict(meta),
            "items": list(items),
        }

    def _load_wix_meta(self, order_reference: str) -> None:
        self._load_wix_context(order_reference)

    def _on_wix_meta_loaded(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        requested_ref = str(data.get("__requested_ref") or "").strip()
        selected = self._selected_summary()
        current_ref = selected.order_reference.strip() if selected is not None else ""
        if requested_ref and requested_ref != current_ref:
            return
        if not data:
            self._reset_wix_meta("Wix-Order nicht gefunden")
            return
        if data.get("status"):
            self._reset_wix_meta(str(data.get("status")))
            return
        self._wix_order_no.setText(data.get("wix_order_number") or data.get("wix_order_id") or "—")
        self._wix_customer.setText(data.get("wix_customer_name") or "—")
        self._wix_customer_email.setText(data.get("wix_customer_email") or "—")
        shipping_country = str(data.get("wix_shipping_country") or "").strip()
        if shipping_country:
            self._dl_country.setText(shipping_country)
        shipping_lines = self._normalize_shipping_lines(
            str(data.get("wix_shipping_address") or "").splitlines()
        )
        if not shipping_lines:
            city = data.get("wix_shipping_city") or ""
            country = data.get("wix_shipping_country") or ""
            shipping_lines = self._normalize_shipping_lines(
                [" ".join(part for part in (city, country) if part)]
            )
        shipping_country = str(data.get("wix_shipping_country") or "").strip()
        if not str(self._dl_country.text() or "").strip():
            if shipping_country:
                self._dl_country.setText(shipping_country)
            elif shipping_lines:
                self._dl_country.setText(str(shipping_lines[-1] or "").strip())
        self._shipping_source_lines = shipping_lines
        self._shipping_status.setText("")
        selected = self._selected_summary()
        override_lines: list[str] = []
        if selected is not None:
            override_lines = list(self._shipping_address_overrides.get(selected.id, []))
        current_lines = self._current_shipping_lines()
        if override_lines:
            self._set_shipping_editor_lines(override_lines)
        elif self._should_replace_shipping_lines(current_lines, shipping_lines):
            self._set_shipping_editor_lines(shipping_lines)
        elif current_lines and shipping_lines and current_lines != shipping_lines:
            self._shipping_status.setText("Versandadresse aus Rechnung verwendet; Wix-Adresse abweichend/unsicher")

    def _on_wix_meta_error(self, exc: Exception) -> None:
        if not self._current_shipping_lines():
            self._shipping_status.setText(f"Wix-Fehler: {exc}")
        logger.warning("Wix meta load failed: %s", exc)

    def _update_plc_controls(self) -> None:
        selected = self._selected_summary()
        enabled = self._print_allowed and (selected is not None)
        self._btn_print.setEnabled(enabled)
        self._btn_print_plc.setEnabled(enabled)
        self._btn_print_music.setEnabled(enabled)
        self._btn_print_label.setEnabled(enabled and len(self._current_shipping_lines()) >= 2)
        self._btn_send_invoice.setEnabled(selected is not None)

        self._selected_plc_label_path = ""
        if selected is not None:
            self._selected_plc_label_path = self._resolve_plc_archive_path_for_summary(selected)
        has_archived_plc = bool(self._selected_plc_label_path)
        self._btn_open_plc_label.setVisible(has_archived_plc)
        self._btn_open_plc_label.setEnabled(has_archived_plc)

    @staticmethod
    def _normalize_shipping_lines(lines: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for line in lines or []:
            text = str(line or "").strip()
            if text and text != "—":
                normalized.append(text)
        return normalized

    def _set_shipping_editor_lines(self, lines: list[str] | None) -> None:
        content = "\n".join(self._normalize_shipping_lines(lines))
        self._shipping_editor.blockSignals(True)
        self._shipping_editor.setPlainText(content)
        self._shipping_editor.blockSignals(False)
        self._adjust_shipping_editor_height()
        self._update_plc_controls()

    def _current_shipping_lines(self) -> list[str]:
        return self._normalize_shipping_lines(self._shipping_editor.toPlainText().splitlines())

    @classmethod
    def _should_replace_shipping_lines(cls, current_lines: list[str], candidate_lines: list[str]) -> bool:
        current = cls._normalize_shipping_lines(current_lines)
        candidate = cls._normalize_shipping_lines(candidate_lines)
        if not candidate:
            return False
        if not current:
            return True
        return cls._address_quality_score(candidate) > cls._address_quality_score(current)

    @staticmethod
    def _address_quality_score(lines: list[str]) -> int:
        normalized = [str(line or "").strip() for line in lines if str(line or "").strip()]
        if not normalized:
            return 0
        score = min(len(normalized), 5)
        has_street = any(re.search(r"\d", line) and not re.match(r"^\d{4,6}\b", line) for line in normalized[1:])
        has_postal_city = any(re.search(r"\b\d{4,6}\b", line) and re.search(r"[A-Za-z]", line) for line in normalized)
        has_country = len(normalized) >= 3 and bool(re.match(r"^[A-Z][A-Z\s.-]{1,}$", normalized[-1]))
        if has_street:
            score += 5
        if has_postal_city:
            score += 4
        if has_country:
            score += 2
        if len(normalized) <= 1:
            score -= 8
        return score

    def _adjust_shipping_editor_height(self) -> None:
        lines = max(5, min(7, self._shipping_editor.blockCount()))
        line_height = self._shipping_editor.fontMetrics().lineSpacing()
        target = max(104, min(150, 18 + lines * line_height))
        self._shipping_editor.setFixedHeight(target)

    def _on_shipping_editor_changed(self) -> None:
        summary = self._selected_summary()
        self._adjust_shipping_editor_height()
        if summary is None:
            self._update_plc_controls()
            return
        edited = self._current_shipping_lines()
        original = self._normalize_shipping_lines(self._shipping_source_lines)
        if edited and edited != original:
            self._shipping_address_overrides[summary.id] = edited
            self._shipping_status.setText("Adresse manuell angepasst")
        else:
            self._shipping_address_overrides.pop(summary.id, None)
            if original:
                self._shipping_status.setText("")
        self._update_plc_controls()

    def _on_direct_label_print_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice_id = str(data.get("invoice_id") or "").strip()
        invoice = str(data.get("invoice") or "---")
        self._apply_fulfillment_flags_to_row(invoice_id, data.get("flags"))
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(f"Label fuer Rechnung {invoice} wurde gesendet.", 5000)

    def _on_direct_label_print_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Labeldruck",
            f"Label konnte nicht gedruckt werden:\n\n{exc}",
        )

    def _on_direct_invoice_print_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice_id = str(data.get("invoice_id") or "").strip()
        invoice = str(data.get("invoice") or "---")
        self._apply_fulfillment_flags_to_row(invoice_id, data.get("flags"))
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(f"Rechnung {invoice} wurde an den Drucker gesendet.", 5000)

    def _on_direct_invoice_print_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rechnungsdruck",
            f"Rechnung konnte nicht gedruckt werden:\n\n{exc}",
        )

    def _on_send_invoice_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice_id = str(data.get("invoice_id") or "").strip()
        invoice = str(data.get("invoice") or "---")
        recipient = str(data.get("recipient") or "---")
        self._apply_fulfillment_flags_to_row(invoice_id, data.get("flags"))
        QMessageBox.information(
            self,
            "Rechnung gesendet",
            f"Rechnung {invoice} wurde an {recipient} gesendet.",
        )

    def _on_send_invoice_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rechnung senden",
            f"Rechnung konnte nicht gesendet werden:\n\n{exc}",
        )

    def _on_send_invoice_finished(self) -> None:
        self._invoice_mail_worker = None
        self._clear_detail_actions_busy()

    def _on_create_draft_clicked(self) -> None:
        if (
            (self._draft_worker is not None and self._draft_worker.isRunning())
            or (self._draft_product_worker is not None and self._draft_product_worker.isRunning())
        ):
            return
        dlg = _DraftInvoiceDialog(self)
        dlg.on_preview_requested(lambda: self._run_draft_preview(dlg))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        order_number = dlg.wix_order_number
        self._open_draft_after_create = dlg.open_in_sevdesk
        self._pending_draft_order_number = order_number
        self._overlay.show_with_message("Produktprüfung wird vorbereitet…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> ProductPreflightPlan:
            service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            return service.build_missing_product_plan([order_number])

        self._draft_product_worker = BackgroundWorker(job)
        self._draft_product_worker.signals.result.connect(self._on_draft_product_plan_ready)
        self._draft_product_worker.signals.error.connect(self._on_create_draft_error)
        self._draft_product_worker.signals.finished.connect(self._on_draft_product_plan_finished)
        self._draft_product_worker.start()

    def _on_create_draft_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        draft_payload = data.get("draft") if isinstance(data.get("draft"), dict) else data
        apply_result = data.get("apply")
        invoice_id = str(draft_payload.get("invoice_id") or "").strip()
        invoice_number = str(draft_payload.get("invoice_number") or "").strip()
        wix_order_number = str(draft_payload.get("wix_order_number") or "").strip()
        positions = str(draft_payload.get("positions") or "0")
        message_lines = [
            f"Wix-Order-Nr: {wix_order_number}",
            f"Rechnung: {invoice_number}",
            f"sevDesk-ID: {invoice_id}",
            f"Positionen: {positions}",
        ]
        if isinstance(apply_result, ProductPreflightApplyResult):
            if apply_result.created_skus:
                message_lines.append("")
                message_lines.append("Neu in sevDesk angelegt:")
                for sku in apply_result.created_skus:
                    message_lines.append(f"- {sku}")
            if apply_result.warnings:
                message_lines.append("")
                message_lines.append("Hinweise:")
                for warning in apply_result.warnings:
                    message_lines.append(f"- {warning}")
        QMessageBox.information(
            self,
            "Rechnungs-Entwurf erstellt",
            "\n".join(message_lines),
        )
        if self._open_draft_after_create and invoice_id:
            base = str(self._container.config.sevdesk.base_url or "https://my.sevdesk.de/api/v1").strip().rstrip("/")
            if base.endswith("/api/v1"):
                base = base[:-7]
            url = f"{base}/#/invoices/{invoice_id}"
            QDesktopServices.openUrl(QUrl(url))
        self._reload_first_page()

    def _on_create_draft_error(self, exc: Exception) -> None:
        self._overlay.hide()
        QMessageBox.warning(
            self,
            "Rechnungs-Entwurf fehlgeschlagen",
            f"Der Entwurf konnte nicht erstellt werden:\n\n{exc}",
        )

    def _on_create_draft_finished(self) -> None:
        self._overlay.hide()

    def _on_draft_product_plan_ready(self, result: object) -> None:
        plan = result if isinstance(result, ProductPreflightPlan) else ProductPreflightPlan(issues=[], part_categories=[])
        decisions = self._run_product_preflight_dialogs(plan)
        self._overlay.show_with_message("Rechnungsentwurf wird erstellt…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, object]:
            service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            apply_result = service.apply_missing_product_plan(plan, decisions) if plan.issues else ProductPreflightApplyResult()
            draft_result = service.create_draft_from_wix_order_number(self._pending_draft_order_number)
            return {"draft": draft_result, "apply": apply_result}

        self._draft_worker = BackgroundWorker(job)
        self._draft_worker.signals.result.connect(self._on_create_draft_result)
        self._draft_worker.signals.error.connect(self._on_create_draft_error)
        self._draft_worker.signals.finished.connect(self._on_create_draft_finished)
        self._draft_worker.start()

    def _on_draft_product_plan_finished(self) -> None:
        self._draft_product_worker = None

    def _run_product_preflight_dialogs(self, plan: ProductPreflightPlan) -> dict[str, ProductIssueDecision]:
        decisions: dict[str, ProductIssueDecision] = {}
        for issue in plan.issues:
            dialog = ProductPreflightDialog(issue, part_categories=plan.part_categories, parent=self)
            decision = dialog.show_dialog()
            if decision is None:
                decision = ProductIssueDecision(action="skip", draft=issue.draft)
            decisions[issue.sku] = decision
        return decisions

    def _run_draft_preview(self, dlg: _DraftInvoiceDialog) -> None:
        reference = dlg.wix_order_number
        if not reference:
            dlg.set_preview_result("Bitte zuerst eine Wix-Order-Nr eingeben.", ok=False)
            return

        if self._draft_preview_worker is not None and self._draft_preview_worker.isRunning():
            self._draft_preview_worker.cancel()
        dlg.set_preview_loading()

        def job() -> tuple[str, dict[str, object]]:
            service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            preview = service.preview_wix_order_number(reference)
            return reference, preview

        self._draft_preview_worker = BackgroundWorker(job)
        worker = self._draft_preview_worker
        worker.signals.result.connect(lambda payload: self._on_draft_preview_result(dlg, payload))
        worker.signals.error.connect(
            lambda exc: dlg.set_preview_result(f"Vorschau fehlgeschlagen:\n{exc}", ok=False)
        )
        worker.signals.finished.connect(
            lambda current=worker: self._on_draft_preview_finished(current)
        )
        worker.start()

    def _on_draft_preview_finished(self, worker: BackgroundWorker) -> None:
        if self._draft_preview_worker is worker:
            self._draft_preview_worker = None

    def _on_draft_preview_result(self, dlg: _DraftInvoiceDialog, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            dlg.set_preview_result("Keine gueltige Vorschau erhalten.", ok=False)
            return
        reference, preview = payload
        if str(reference) != dlg.wix_order_number or not isinstance(preview, dict):
            dlg.set_preview_result("Eingabe wurde geaendert. Bitte Vorschau erneut laden.", ok=False)
            return

        lines: list[str] = []
        lines.append(f"Wix-Order: {preview.get('wix_order_number', '—')}")
        lines.append(f"Kunde: {preview.get('customer', '—')}")
        lines.append(f"E-Mail: {preview.get('email', '—')}")
        lines.append("")
        lines.append("Positionen:")
        items = preview.get("items") if isinstance(preview.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('qty', '1')}x [{item.get('sku', '—')}] {item.get('name', '—')} -> {item.get('status', '—')}"
            )

        missing = preview.get("missing_skus") if isinstance(preview.get("missing_skus"), list) else []
        if missing:
            lines.append("")
            lines.append("Fehlende/ungültige SKU-Mappings:")
            for sku in missing:
                lines.append(f"- {sku}")

        auto_create = preview.get("auto_create_skus") if isinstance(preview.get("auto_create_skus"), list) else []
        if auto_create:
            lines.append("")
            lines.append("Öffnen vor dem Entwurf den Produktdialog:")
            for sku in auto_create:
                lines.append(f"- {sku}")

        can_create = bool(preview.get("can_create"))
        dlg.set_preview_result("\n".join(lines), ok=can_create)

    def _reset_stuecke(self) -> None:
        self._current_piece_blocks = []
        self._piece_print_buttons = []
        self._piece_quantity_inputs = []
        self._piece_quantity_controls = []
        self._piece_model.set_pieces([])
        self._piece_list.hide()
        self._stuecke_hint.setText("—")
        self._stuecke_hint.show()
        self._gb_stuecke.hide()

    def _load_stuecke(self, order_reference: str) -> None:
        self._load_wix_context(order_reference)

    def _on_stuecke_loaded(self, items: object) -> None:
        requested_ref = ""
        payload_items: object = items
        if isinstance(items, dict):
            requested_ref = str(items.get("__requested_ref") or "").strip()
            payload_items = items.get("items")
        selected = self._selected_summary()
        current_ref = selected.order_reference.strip() if selected is not None else ""
        if requested_ref and requested_ref != current_ref:
            return

        self._gb_stuecke.show()
        self._piece_print_buttons = []
        self._piece_quantity_inputs = []
        self._piece_quantity_controls = []
        self._piece_model.set_pieces([])
        self._piece_list.hide()
        self._stuecke_hint.hide()
        if not isinstance(payload_items, list) or not payload_items:
            self._stuecke_hint.setText("Keine Positionen gefunden.")
            self._stuecke_hint.show()
            return
        deduped: list[PieceBlock] = []
        seen: set[tuple[str, str, int, str]] = set()
        for piece in payload_items:
            if not isinstance(piece, PieceBlock):
                continue
            key = (
                str(piece.sku or "").strip().upper(),
                str(piece.name or "").strip(),
                int(piece.qty_needed or 0),
                str(piece.note or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(piece)
        self._current_piece_blocks = deduped
        invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        model_rows: list[dict[str, object]] = []
        for item in self._current_piece_blocks:
            flagged_for_print = bool(item.is_unreleased or invoice_service.is_flagged_sku(item.sku))
            show_print_controls = not (item.product is not None and item.product.is_digital)
            model_rows.append(
                {
                    "block": item,
                    "flagged": bool(flagged_for_print and show_print_controls),
                    "quantity": self._default_piece_print_qty(item),
                    "header": self._piece_header_text(item, flagged_for_print),
                    "details": self._piece_detail_lines(item),
                    "stock": self._piece_stock_text(item),
                    "stock_color": self._piece_stock_color(item),
                    "print_enabled": self._print_allowed,
                }
            )
        self._piece_model.set_pieces(model_rows)
        self._piece_list.show()
        return
        for item in self._current_piece_blocks:
            # Header line: "×2  [XW-001]  Produktname ★"
            flagged_for_print = bool(item.is_unreleased or invoice_service.is_flagged_sku(item.sku))
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 6)
            row_layout.setSpacing(2)
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(8)
            lbl = QLabel(self._piece_header_text(item, flagged_for_print))
            lbl.setWordWrap(True)
            header_row.addWidget(lbl, stretch=1)

            if flagged_for_print:
                qty_input = QSpinBox()
                qty_input.setRange(1, 999)
                qty_input.setValue(self._default_piece_print_qty(item))
                qty_input.setFixedHeight(24)
                qty_input.setFixedWidth(64)
                qty_input.setEnabled(self._print_allowed)
                qty_input.setToolTip("Anzahl fuer diesen Produktdruck")
                header_row.addWidget(qty_input)
                self._piece_quantity_inputs.append(qty_input)
                self._piece_quantity_controls.append((item, qty_input))

                print_btn = QToolButton()
                print_btn.setIcon(QIcon(str(Path(__file__).resolve().parents[5] / "icons" / "print.png")))
                print_btn.setFixedSize(30, 26)
                print_btn.setStyleSheet(
                    "QToolButton { background-color: #334155; border: 1px solid #64748b; border-radius: 4px; }"
                    "QToolButton:hover { background-color: #475569; border-color: #94a3b8; }"
                    "QToolButton:disabled { background-color: #1f2937; border-color: #334155; }"
                )
                print_btn.setEnabled(self._print_allowed)
                if item.has_direct_print_config:
                    print_btn.setToolTip("Direkter Produktdruck ueber hinterlegten Druckplan")
                elif item.print_file_path is not None:
                    print_btn.setToolTip("PDF vorhanden, aber noch kein Druckplan/Profil im neuen Repo hinterlegt")
                else:
                    print_btn.setToolTip("Kein PDF-Pfad im neuen Repo hinterlegt")
                print_btn.clicked.connect(
                    lambda _checked=False, block=item, qty=qty_input: self._on_product_print_clicked(block, qty.value())
                )
                header_row.addWidget(print_btn)
                self._piece_print_buttons.append(print_btn)

                manage_btn = QToolButton()
                manage_btn.setIcon(QIcon(str(Path(__file__).resolve().parents[5] / "icons" / "printondemand.png")))
                manage_btn.setFixedSize(30, 26)
                manage_btn.setStyleSheet(
                    "QToolButton { background-color: #334155; border: 1px solid #64748b; border-radius: 4px; }"
                    "QToolButton:hover { background-color: #475569; border-color: #94a3b8; }"
                    "QToolButton:disabled { background-color: #1f2937; border-color: #334155; }"
                )
                manage_btn.setToolTip("PDF-Pfad und Druckplan direkt fuer dieses Produkt pflegen")
                manage_btn.clicked.connect(lambda _checked=False, block=item: self._on_product_manage_clicked(block))
                header_row.addWidget(manage_btn)

            row_layout.addLayout(header_row)

            for detail_line in self._piece_detail_lines(item):
                detail_lbl = QLabel(detail_line)
                detail_lbl.setWordWrap(True)
                detail_lbl.setStyleSheet("color: #64748b; font-size: 11px; padding-left: 8px;")
                row_layout.addWidget(detail_lbl)

            stock_lbl = QLabel(self._piece_stock_text(item))
            stock_lbl.setWordWrap(True)
            # Colour: red for print-needed, orange for low, green for OK, grey for digital
            if item.product is None:
                color = "#9e9e9e"
            elif item.product.is_digital:
                color = "#64748b"
            elif item.needs_print:
                color = "#ef4444"
            elif item.stock_status is not None and item.stock_status.needs_reprint:
                color = "#f59e0b"
            else:
                color = "#16a34a"
            stock_lbl.setStyleSheet(f"color: {color}; font-size: 11px; padding-left: 8px;")
            row_layout.addWidget(stock_lbl)
            self._stuecke_layout.addWidget(row_widget)

    def _on_product_print_clicked(self, block: PieceBlock, quantity: int | None = None) -> None:
        if not self._print_allowed or (self._product_print_worker is not None and self._product_print_worker.isRunning()):
            return
        from xw_office.ui.modules.rechnungen.print_dialog import prepare_piece_pdf_print

        qty = max(1, int(quantity or self._default_piece_print_qty(block)))
        job = prepare_piece_pdf_print(self, self._container, piece=block, copies=qty, wait=True)
        if job is None:
            return

        row = self._table.selected_source_row()
        invoice_ref = ""
        if row is not None and 0 <= row < len(self._summaries):
            invoice_ref = self._summaries[row].invoice_number or self._summaries[row].id

        self._set_piece_print_controls_enabled(False)
        self._btn_print_music.setEnabled(False)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(f"Produktdruck fuer {block.sku} gestartet ({qty}x).", 5000)

        def worker_job() -> dict[str, object]:
            job()
            if block.product is None or not str(block.product.sevdesk_part_id or "").strip():
                return {
                    "sku": block.sku,
                    "quantity": qty,
                    "stock_warning": "kein sevDesk-Part fuer Bestandsbuchung hinterlegt",
                }
            try:
                engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
                new_stock = engine.record_print_and_update_sevdesk(block, qty, invoice_ref=invoice_ref)
            except Exception as exc:
                logger.warning("Stock update after product print failed: %s", exc)
                return {"sku": block.sku, "quantity": qty, "stock_warning": str(exc)}
            local_warning = ""
            try:
                self._container.resolve(InventoryService).set_product_stock(block.sku, new_stock)
            except Exception as exc:
                local_warning = str(exc)
                logger.warning("Local stock mirror update failed for %s: %s", block.sku, exc)
            return {
                "sku": block.sku,
                "quantity": qty,
                "stock_warning": "",
                "local_warning": local_warning,
            }

        self._product_print_worker = BackgroundWorker(worker_job)
        self._product_print_worker.signals.result.connect(self._on_product_print_result)
        self._product_print_worker.signals.error.connect(self._on_product_print_error)
        self._product_print_worker.signals.finished.connect(self._on_product_print_finished)
        self._product_print_worker.start()

    def _on_product_print_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        sku = str(data.get("sku") or "").strip() or "Produkt"
        qty = str(data.get("quantity") or "").strip() or "?"
        warning = str(data.get("stock_warning") or "").strip()
        local_warning = str(data.get("local_warning") or "").strip()
        signals: AppSignals = self._container.resolve(AppSignals)
        if warning:
            signals.status_message.emit(f"{sku}: Druckauftrag {qty}x bestaetigt; Bestand nicht gebucht.", 8000)
        elif local_warning:
            signals.status_message.emit(
                f"{sku}: Druck bestaetigt und sevDesk gebucht; lokaler Spiegel konnte nicht aktualisiert werden.",
                10000,
            )
        else:
            signals.status_message.emit(f"{sku}: Druckauftrag {qty}x bestaetigt; Bestand aktualisiert.", 5000)

    def _on_product_print_error(self, exc: Exception) -> None:
        QMessageBox.critical(
            self,
            "Produktdruck fehlgeschlagen",
            f"Die Produkt-PDF konnte nicht ueber den hinterlegten Druckplan gedruckt werden:\n\n{exc}",
        )

    def _on_product_print_finished(self) -> None:
        self._product_print_worker = None
        self._set_piece_print_controls_enabled(self._print_allowed)
        self._update_print_all_products_button()
        self._update_plc_controls()

    @staticmethod
    def _default_piece_print_qty(block: PieceBlock) -> int:
        return max(1, int(block.print_qty or block.qty_needed or 1))

    def _set_piece_print_controls_enabled(self, enabled: bool) -> None:
        self._piece_model.set_print_enabled(enabled)
        self._piece_list.viewport().update()
        for button in self._piece_print_buttons:
            button.setEnabled(enabled)
        for qty_input in self._piece_quantity_inputs:
            qty_input.setEnabled(enabled)

    def _on_product_manage_clicked(self, block: PieceBlock) -> None:
        from xw_office.ui.modules.rechnungen.print_dialog import _configure_missing_piece_print

        if _configure_missing_piece_print(self, self._container, block):
            signals: AppSignals = self._container.resolve(AppSignals)
            signals.status_message.emit(f"Druckkonfiguration fuer {block.sku} gespeichert.", 5000)
            self._on_stuecke_loaded(self._current_piece_blocks)
            return
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"Druckkonfiguration fuer {block.sku} nicht geaendert.",
            5000,
        )

    @staticmethod
    def _piece_header_text(block: PieceBlock, flagged_for_print: bool) -> str:
        marker = " ★" if flagged_for_print else ""
        return f"×{block.qty_needed}  [{block.sku}]  {block.name}{marker}"

    @staticmethod
    def _piece_detail_lines(block: PieceBlock) -> list[str]:
        note = str(block.note or "").strip()
        if not note:
            return []
        parts = [part.strip() for part in note.split(" | ") if part.strip()]
        sku = str(block.sku or "").strip().upper()
        if sku in {"XW-010", "XW-011"}:
            return [
                part
                for part in parts
                if not normalize_legacy_title(part).startswith("name des stuckes der stucke")
            ]
        return parts

    @staticmethod
    def _piece_stock_text(block: PieceBlock) -> str:
        if block.product is None:
            return "Produkt im neuen Repo noch nicht gepflegt"
        if block.product.is_digital:
            return "Digital"
        if block.stock_status is None:
            qty = max(1, int(block.print_qty or block.qty_needed or 1))
            return f"Bestand unbekannt – {qty}x drucken"
        on_hand = int(block.stock_status.on_hand)
        if on_hand <= 0:
            qty = max(1, int(block.print_qty or block.qty_needed or 1))
            return f"Leer – {qty}x drucken"
        if block.needs_print:
            qty = max(1, int(block.print_qty or block.qty_needed or 1))
            return f"Zu wenig ({on_hand} Stk) – {qty}x drucken"
        if block.stock_status.needs_reprint:
            return f"Niedriger Bestand ({on_hand} Stk)"
        return f"Im Lager ({on_hand} Stk)"

    @staticmethod
    def _piece_stock_color(block: PieceBlock) -> str:
        if block.product is None:
            return "#9e9e9e"
        if block.product.is_digital:
            return "#64748b"
        if block.needs_print:
            return "#ef4444"
        if block.stock_status is not None and block.stock_status.needs_reprint:
            return "#f59e0b"
        return "#16a34a"

    @staticmethod
    def _describe_piece_print_config(block: PieceBlock) -> str:
        path = block.print_file_path
        if path is None:
            return "kein PDF-Pfad hinterlegt"
        if block.print_plan:
            parts: list[str] = []
            for entry in block.print_plan:
                if not isinstance(entry, dict):
                    continue
                range_text = str(entry.get("range") or "").strip() or "Alle Seiten"
                profile_id = str(entry.get("profile_id") or "").strip() or "?"
                parts.append(f"{range_text} -> {profile_id}")
            return " / ".join(parts) if parts else "Print-Plan vorhanden"
        if str(block.print_profile_id or "").strip():
            return f"Profil {block.print_profile_id}"
        return "PDF vorhanden, aber kein Druckplan"

    def _on_stuecke_error(self, exc: Exception) -> None:
        logger.warning("Stücke fetch failed: %s", exc)
        self._stuecke_hint.setText(f"Fehler: {exc}")
        self._stuecke_hint.show()
