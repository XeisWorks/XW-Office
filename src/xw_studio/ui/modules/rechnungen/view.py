"""Rechnungen module — invoice list from sevDesk."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import time
from pathlib import Path
from urllib.parse import quote
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
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
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.printer_detect import discover_printers, evaluate_printer_status
from xw_studio.core.types import PrinterStatus
from xw_studio.core.types import ModuleKey
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.draft_invoice.service import (
    DraftInvoiceService,
    ProductIssueDecision,
    ProductPreflightApplyResult,
    ProductPreflightPlan,
)
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sendungen.service import OffeneSendungenService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.sevdesk.refund_client import SevDeskRefundClient
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.ui.modules.rechnungen.offene_sendungen_dialog import OffeneSendungenDialog
from xw_studio.ui.modules.rechnungen.plc_label_dialog import PlcLabelPrintDialog
from xw_studio.ui.modules.rechnungen.product_preflight_dialog import ProductPreflightDialog
from xw_studio.ui.modules.rechnungen.refund_dialog import RefundDialog
from xw_studio.ui.widgets.data_table import DataTable
from xw_studio.ui.widgets.progress_overlay import ProgressOverlay
from xw_studio.ui.widgets.search_bar import SearchBar
from xw_studio.ui.widgets.toolbar import Toolbar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

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

_PAGE_SIZE = 50
_DRAFT_STATUS = 100
_OPEN_STATUS = 200
_OPEN_AUTO_LOAD_LIMIT = 30
# Contexts are immutable enough for one application session.  The persistent
# Wix snapshot cache is retained for 180 days; dropping the UI representation
# after 75 seconds only caused needless conversion work when users revisited a
# row in the same list.
_WIX_CONTEXT_CACHE_TTL_SECONDS = 6 * 60 * 60
_WIX_WARM_BATCH_SIZE = 6
_WIX_WARM_MAX_WORKERS = 4


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
        self._preview.setPlainText(text)
        self._preview_ok = ok
        if ok:
            self._status.setText("Vorschau OK: Entwurf kann erstellt werden.")
            self._status.setStyleSheet("color: #15803d;")
        else:
            self._status.setText("Vorschau enthält Probleme. Entwurf wird blockiert.")
            self._status.setStyleSheet("color: #b91c1c;")

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
            from xw_studio.services.printing.label_printer import LabelPrinter
            from xw_studio.services.printing.print_queue import PrintQueueService

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


class RechnungenView(QWidget):
    """Load and display sevDesk invoices (non-blocking)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._search_worker: BackgroundWorker | None = None
        self._refund_worker: BackgroundWorker | None = None
        self._draft_worker: BackgroundWorker | None = None
        self._draft_product_worker: BackgroundWorker | None = None
        self._mollie_badge_worker: BackgroundWorker | None = None
        self._stuecke_worker: BackgroundWorker | None = None
        self._wix_meta_worker: BackgroundWorker | None = None
        self._wix_context_worker: BackgroundWorker | None = None
        self._invoice_detail_worker: BackgroundWorker | None = None
        self._customer_mail_worker: BackgroundWorker | None = None
        self._wix_warm_worker: BackgroundWorker | None = None
        self._hint_worker: BackgroundWorker | None = None
        self._fulfillment_step_worker: BackgroundWorker | None = None
        self._invoice_mail_worker: BackgroundWorker | None = None
        self._open_overview_worker: BackgroundWorker | None = None
        self._product_print_worker: BackgroundWorker | None = None
        self._did_initial_load = False
        self._print_allowed = False
        self._open_draft_after_create = False
        self._pending_draft_order_number = ""
        self._mollie_alert_count = 0
        self._sendungen_alert_count = 0
        self._search_index: list[dict[str, str]] = []
        self._loaded_rows: list[dict[str, Any]] = []
        self._loaded_summaries: list[InvoiceSummary] = []
        self._loaded_has_more = False
        self._active_load_status = _DRAFT_STATUS
        self._draft_offset = 0
        self._open_offset = 0
        self._draft_has_more = False
        self._open_has_more = False
        self._open_loaded = False
        self._pending_auto_open_load = False
        self._load_started_at = 0.0
        self._wix_warm_started_at = 0.0
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
        self._open_overview_seq = 0
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
        self._append_mode = False
        self._queued_wix_context_ref = ""
        self._queued_invoice_detail_id = ""
        self._table_layout_initialized = False
        self._open_overview_key = ""
        self._open_overview_cached_physical = 0
        self._open_overview_cached_digital = 0
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
        self._actions_delegate = _ActionsDelegate(self._table)
        self._fulfillment_delegate = _FulfillmentDelegate(self._table)
        status_col = 3
        hint_col = _TABLE_COLUMNS.index("Hinweise")
        fulfillment_col = _TABLE_COLUMNS.index("FULFILLMENT")
        actions_col = _TABLE_COLUMNS.index("AKTIONEN")
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
        self._gb_actions.hide()
        detail_main.addWidget(self._gb_actions)

        self._gb_stuecke = QGroupBox("Produkte")
        self._stuecke_layout = QVBoxLayout(self._gb_stuecke)
        self._stuecke_layout.setSpacing(4)
        self._stuecke_hint = QLabel("—")
        self._stuecke_hint.setWordWrap(True)
        self._stuecke_layout.addWidget(self._stuecke_hint)
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
        self._initialize_printer_status()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._did_initial_load:
            self._did_initial_load = True
            if self._has_sevdesk_token():
                self._reload_first_page()
        if not self._badge_refresh_managed_externally:
            self._refresh_mollie_alert_count()
            self._mollie_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
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
        self._mollie_timer.stop()
        self._stop_mollie_worker()
        super().closeEvent(event)

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

    def open_sendungen_dialog(self) -> int:
        dlg = OffeneSendungenDialog(self._container, self)
        dlg.exec()
        count = dlg.open_count()
        self.update_sendungen_alert_count(count)
        return count

    def open_queue_dialog(self, queue_name: str, title: str, fallback_count: int = 0) -> None:
        from xw_studio.ui.modules.rechnungen.tagesgeschaeft_view import QueuePopupDialog

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
        if self._mollie_badge_worker is not None and self._mollie_badge_worker.isRunning():
            self._mollie_badge_worker.wait(1000)

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
        self._update_plc_controls()

    def _initialize_printer_status(self) -> None:
        names = list(self._container.config.printing.configured_printer_names)
        discovered = discover_printers()
        status = evaluate_printer_status(discovered, names)
        self._on_printer_status(status != PrinterStatus.RED)

    def _reload_first_page(self) -> None:
        self._next_offset = 0
        self._active_load_status = _DRAFT_STATUS
        self._draft_offset = 0
        self._open_offset = 0
        self._draft_has_more = False
        self._open_has_more = False
        self._open_loaded = False
        self._append_mode = False
        self._start_load()

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
            "Rechnungen load start status=%s limit=%s offset=%s append=%s",
            status_filter,
            page_limit,
            offset,
            append,
        )

        self._overlay.show_with_message(
            "Rechnungen werden geladen…" if not append else "Weitere Rechnungen werden geladen…",
        )
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> tuple[list[dict[str, str]], list[InvoiceSummary], bool, int]:
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
        status_filter = int(status_obj)
        elapsed_ms = int((time.perf_counter() - self._load_started_at) * 1000) if self._load_started_at else 0
        logger.info(
            "Rechnungen load result status=%s rows=%s has_more=%s elapsed_ms=%s",
            status_filter,
            len(summaries),
            has_more,
            elapsed_ms,
        )
        self._prepare_rows_for_hint_prefetch(rows, summaries)

        if self._append_mode:
            self._table.append_rows(rows)
            self._summaries.extend(summaries)
        else:
            self._table.set_data(rows)
            self._summaries = summaries
            self._loaded_rows = rows
            self._loaded_summaries = summaries
            self._loaded_has_more = has_more

        if status_filter == _DRAFT_STATUS:
            self._draft_offset = sum(
                1 for summary in self._summaries if summary.status_code == _DRAFT_STATUS
            )
            self._draft_has_more = has_more
        elif status_filter == _OPEN_STATUS:
            self._open_loaded = True
            self._open_offset = sum(
                1 for summary in self._summaries if summary.status_code == _OPEN_STATUS
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
        self._refresh_open_invoice_overview()

        self._next_offset = len(self._summaries)
        self._update_load_more_button()

        signals: AppSignals = self._container.resolve(AppSignals)
        mode = "angehaengt" if self._append_mode else "geladen"
        signals.status_message.emit(
            f"{len(rows)} Rechnungen {mode} ({self._next_offset} gesamt in Liste)",
            5000,
        )
        self._append_mode = False
        self._refresh_detail_for_selection()
        self._warm_wix_context_for_summaries(summaries)
        if status_filter != _OPEN_STATUS:
            self._restart_hint_prefetch()
        if auto_load_open:
            logger.info("Rechnungen auto-open-load queued limit=%s", _OPEN_AUTO_LOAD_LIMIT)
            self._pending_auto_open_load = True

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
                self._btn_more.setToolTip("Offene Rechnungen laden")
                self._btn_more.setEnabled(True)
            else:
                self._btn_more.setText("Keine weiteren")
                self._btn_more.setToolTip("Keine weiteren Rechnungen in dieser Ansicht")
                self._btn_more.setEnabled(False)
            return
        if self._open_has_more:
            self._btn_more.setText("Weitere Rechnungen laden")
            self._btn_more.setToolTip(f"Naechste bis zu {_PAGE_SIZE} offene Rechnungen anhaengen")
            self._btn_more.setEnabled(True)
        else:
            self._btn_more.setText("Keine weiteren")
            self._btn_more.setToolTip("Keine weiteren offenen Rechnungen")
            self._btn_more.setEnabled(False)

    def _apply_table_column_layout(self) -> None:
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        for idx in range(len(_TABLE_COLUMNS)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        self._table.resizeColumnsToContents()
        for idx in range(len(_TABLE_COLUMNS)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)

    def _refresh_mollie_alert_count(self) -> None:
        if self._mollie_badge_worker is not None and self._mollie_badge_worker.isRunning():
            return

        def job() -> dict[str, int]:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            counts = service.load_counts(open_invoice_count=0)
            sendungen_service: OffeneSendungenService = self._container.resolve(OffeneSendungenService)
            return {
                "mollie": max(0, int(counts.get("mollie", 0))),
                "sendungen": max(0, int(sendungen_service.open_count())),
            }

        self._mollie_badge_worker = BackgroundWorker(job)
        self._mollie_badge_worker.signals.result.connect(self._on_mollie_badge_result)
        self._mollie_badge_worker.start()

    def _on_mollie_badge_result(self, result: object) -> None:
        if isinstance(result, dict):
            mollie = max(0, int(result.get("mollie") or 0))
            sendungen = max(0, int(result.get("sendungen") or 0))
        else:
            mollie = max(0, int(result)) if isinstance(result, int) else 0
            sendungen = 0
        self.update_mollie_alert_count(mollie)
        self.update_sendungen_alert_count(sendungen)

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

    def _on_mollie_alert_clicked(self) -> None:
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.navigate_to_module.emit(ModuleKey.MOLLIE.value)

    def _on_sendungen_alert_clicked(self) -> None:
        dlg = OffeneSendungenDialog(self._container, self)
        dlg.exec()
        self.update_sendungen_alert_count(dlg.open_count())

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
            self._populate_detail_for_summary(summaries[0])
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
        total = len(open_rows)
        with_ref = sum(1 for s in open_rows if s.order_reference.strip())
        plc = sum(1 for s in open_rows if s.has_plc_label_candidate())
        with_note = sum(1 for s in open_rows if s.buyer_note.strip())
        refs = [s.order_reference.strip() for s in open_rows]
        overview_key = "|".join(sorted(refs))

        self._open_total.setText(str(total))
        self._open_with_ref.setText(str(with_ref))
        self._open_plc.setText(str(plc))
        self._open_note.setText(str(with_note))

        if total == 0:
            self._open_physical.setText("0")
            self._open_digital.setText("0")
            self._open_overview_key = ""
            self._open_overview_cached_physical = 0
            self._open_overview_cached_digital = 0
            return

        if overview_key and overview_key == self._open_overview_key:
            self._open_physical.setText(str(self._open_overview_cached_physical))
            self._open_digital.setText(str(self._open_overview_cached_digital))
            return

        known_refs = [ref for ref in refs if ref and ref in self._wix_digital_cache]
        physical = sum(1 for ref in known_refs if not self._wix_digital_cache.get(ref))
        digital = sum(1 for ref in known_refs if self._wix_digital_cache.get(ref))
        unknown = max(0, with_ref - len(known_refs))
        self._open_overview_key = overview_key
        self._open_overview_cached_physical = physical
        self._open_overview_cached_digital = digital
        suffix = "+" if unknown else ""
        self._open_physical.setText(f"{physical}{suffix}")
        self._open_digital.setText(f"{digital}{suffix}")

    def _on_open_overview_result(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        seq = int(payload.get("seq") or 0)
        if seq != self._open_overview_seq:
            return
        cache_updates = payload.get("cache_updates")
        if isinstance(cache_updates, dict):
            for key, value in cache_updates.items():
                self._wix_digital_cache[str(key)] = bool(value)
        physical = int(payload.get("physical") or 0)
        digital = int(payload.get("digital") or 0)
        self._open_overview_key = str(payload.get("overview_key") or "")
        self._open_overview_cached_physical = max(0, physical)
        self._open_overview_cached_digital = max(0, digital)
        self._open_physical.setText(str(max(0, physical)))
        self._open_digital.setText(str(max(0, digital)))

    def _on_open_overview_error(self, exc: Exception) -> None:
        logger.warning("Open-overview digital classification failed: %s", exc)
        with_ref = int(self._open_with_ref.text() or "0") if self._open_with_ref.text().isdigit() else 0
        total = int(self._open_total.text() or "0") if self._open_total.text().isdigit() else 0
        self._open_overview_cached_physical = with_ref
        self._open_overview_cached_digital = max(0, total - with_ref)
        self._open_physical.setText(str(self._open_overview_cached_physical))
        self._open_digital.setText(str(self._open_overview_cached_digital))

    def _warm_wix_context_for_summaries(self, summaries: list[InvoiceSummary]) -> None:
        """Prefetch full Wix contexts without delaying the invoice list.

        Only active drafts are warmed: historical invoices are fetched when the
        user selects them. Each small batch uses bounded concurrency so the
        right-hand panel is ready quickly without putting excessive pressure on
        the Wix API.
        """
        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        added = 0
        for summary in summaries:
            if summary.status_code != _DRAFT_STATUS:
                continue
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
        if added:
            logger.info(
                "Wix context warmup queued refs=%s pending=%s",
                added,
                len(self._wix_warm_queue),
            )
        self._start_next_wix_warm_batch()

    def _start_next_wix_warm_batch(self) -> None:
        if self._wix_warm_worker is not None and self._wix_warm_worker.isRunning():
            return
        if not self._wix_warm_queue:
            return

        refs = self._wix_warm_queue[:_WIX_WARM_BATCH_SIZE]
        del self._wix_warm_queue[:_WIX_WARM_BATCH_SIZE]
        self._wix_warm_inflight_refs = set(refs)
        self._wix_warm_started_at = time.perf_counter()
        logger.info("Wix context warmup start refs=%s pending=%s", len(refs), len(self._wix_warm_queue))

        def job() -> list[dict[str, object]]:
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
            def warm_one(ref: str) -> dict[str, object]:
                try:
                    # All three operations share WixOrdersClient's persistent
                    # read-through cache, so only the first one can hit Wix.
                    meta = wix_client.resolve_order_summary(ref)
                    wix_items = wix_client.fetch_order_line_items(ref)
                    pieces = engine.get_piece_blocks(wix_items, invoice_ref=ref)
                    hints = invoice_service.resolve_invoice_list_hints(ref)
                    return {
                        "reference": ref,
                        "status": "" if meta else "Wix-Order nicht gefunden",
                        "meta": meta if isinstance(meta, dict) else {},
                        "items": pieces,
                        "patch": hints.as_row_patch(),
                    }
                except Exception as exc:  # noqa: BLE001 - warmup must not affect the list.
                    logger.warning("Wix warmup failed ref=%s: %s", ref, exc)
                    return {
                        "reference": ref,
                        "status": f"Wix-Fehler: {exc}",
                        "meta": {},
                        "items": [],
                        "patch": self._blank_hint_patch(),
                    }

            workers = min(_WIX_WARM_MAX_WORKERS, len(refs))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wix-warm") as executor:
                return list(executor.map(warm_one, refs))

        self._wix_warm_worker = BackgroundWorker(job)
        self._wix_warm_worker.signals.result.connect(self._on_wix_warm_result)
        self._wix_warm_worker.signals.error.connect(self._on_wix_warm_error)
        self._wix_warm_worker.signals.finished.connect(self._on_wix_warm_finished)
        self._wix_warm_worker.start()

    def _on_wix_warm_result(self, payload: object) -> None:
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
        self._wix_warm_inflight_refs.clear()
        self._start_next_wix_warm_batch()

    def _restart_hint_prefetch(self) -> None:
        self._hint_seq += 1
        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        draft_refs: list[str] = []
        seen: set[str] = set()
        for summary in self._summaries:
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
        if self._hint_worker is not None and self._hint_worker.isRunning():
            return
        ref = ""
        if self._hint_draft_queue:
            ref = self._hint_draft_queue.pop(0)
        elif self._hint_rest_queue:
            ref = self._hint_rest_queue.pop(0)
        if not ref:
            self._hint_inflight_ref = ""
            return
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
        self._hint_worker.start()

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

    def _on_print_clicked(self) -> None:
        if not self._print_allowed:
            return
        summary = self._require_selected_invoice()
        if summary is None:
            return
        if self._fulfillment_step_worker is not None and self._fulfillment_step_worker.isRunning():
            return

        self._overlay.show_with_message("Rechnungsdruck laeuft...")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            flags = service.print_invoice_for_invoice(summary.id)
            return {
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

        self._overlay.show_with_message("Labeldruck läuft…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            flags = service.print_label_for_invoice(summary.id, override_lines=shipping_lines)
            return {
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
        from xw_studio.ui.modules.rechnungen.print_dialog import run_plc_label_pdf_print

        run_plc_label_pdf_print(
            self,
            self._container,
            invoice_number=summary.invoice_number,
        )
        self._last_plc_invoice = summary.invoice_number or summary.id
        self._plc_last.setText(f"Letzter PLC-Druck: {self._last_plc_invoice}")

    def _open_plc_post_popup(self, summary: InvoiceSummary) -> None:
        selected = self._selected_summary()
        if selected is not None and selected.id == summary.id:
            address_lines = self._current_shipping_lines()
            recipient_email = str(self._wix_customer_email.text() or "").strip()
            if recipient_email in {"—", "---"}:
                recipient_email = ""
        else:
            address_lines = list(self._shipping_address_overrides.get(summary.id, []))
            recipient_email = ""
        dlg = PlcLabelPrintDialog(
            self._container,
            summary,
            self,
            address_override_lines=address_lines,
            recipient_email=recipient_email,
        )
        dlg.exec()

    def _on_print_music_clicked(self) -> None:
        if not self._print_allowed:
            return
        if self._require_selected_invoice() is None:
            return
        if self._product_print_worker is not None and self._product_print_worker.isRunning():
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import prepare_piece_pdf_print

        selected_jobs: list[tuple[PieceBlock, int, Callable[[], None]]] = []
        skipped: list[str] = []
        for block, qty_input in self._piece_quantity_controls:
            qty = max(1, int(qty_input.value() or self._default_piece_print_qty(block)))
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

        self._overlay.show_with_message("Rechnungsmail wird gesendetâ€¦")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            flags, recipient, subject = service.send_invoice_mail_for_invoice(summary)
            return {
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
        self._table.selectRow(row)

    def eventFilter(self, watched: Any, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self._table.viewport() and event.type() in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Leave,
        ):
            if event.type() == QEvent.Type.Leave:
                self._table.viewport().unsetCursor()
                return super().eventFilter(watched, event)
            if isinstance(event, QMouseEvent):
                index = self._table.indexAt(event.position().toPoint())
                if index.isValid():
                    actions_col = _TABLE_COLUMNS.index("AKTIONEN")
                    if event.type() == QEvent.Type.MouseMove:
                        if int(index.column()) == actions_col:
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

                    self._table.selectRow(int(index.row()))
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
        if chip == "payment_booked":
            QMessageBox.information(self, "Payment", "Payment-Flow ist aktuell noch deaktiviert.")
            return
        if self._fulfillment_step_worker is not None and self._fulfillment_step_worker.isRunning():
            return

        labels = {
            "label_printed": "Label",
            "invoice_printed": "Rechnung",
            "product_ready": "Produkt",
            "mail_sent": "Mail",
            "wix_fulfilled": "Wix",
        }
        self._overlay.show_with_message(f"Retry {labels.get(chip, chip)} läuft…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        invoice_id = summary.id

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            updated = service.retry_fulfillment_step(invoice_id, chip)
            payload = updated.as_row_payload() if hasattr(updated, "as_row_payload") else {}
            return {
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
        invoice = str(data.get("invoice") or "—")
        chip = str(data.get("chip") or "")
        QMessageBox.information(
            self,
            "Fulfillment aktualisiert",
            f"Rechnung {invoice}: Schritt '{chip}' wurde erneut ausgeführt.",
        )
        self._reload_first_page()

    def _on_fulfillment_step_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Fulfillment-Fehler",
            f"Schritt konnte nicht ausgeführt werden:\n\n{exc}",
        )

    def _on_fulfillment_step_finished(self) -> None:
        self._overlay.hide()

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

    def _open_customer_mail(self, summary: InvoiceSummary) -> None:
        email = self._customer_email_from_loaded_context(summary)
        if email:
            self._open_customer_mail_url(summary, email)
            return
        if self._customer_mail_worker is not None and self._customer_mail_worker.isRunning():
            QMessageBox.information(self, "Kunden-Mail", "Eine Kunden-Mail wird bereits vorbereitet.")
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Kunden-Mail wird vorbereitet…", 2500)

        def job() -> dict[str, str]:
            resolved_email = ""
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
            return {
                "invoice_id": str(summary.id or "").strip(),
                "email": resolved_email,
                "invoice_number": str(summary.invoice_number or "").strip(),
                "order_reference": str(summary.order_reference or "").strip(),
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
        self._open_customer_mail_url(summary, email)

    def _on_customer_mail_error(self, exc: Exception) -> None:
        QMessageBox.warning(self, "Kunden-Mail", f"Mail konnte nicht vorbereitet werden:\n\n{exc}")

    def _open_customer_mail_url(self, summary: InvoiceSummary, email: str) -> None:
        clean_email = self._clean_email_value(email)
        if not clean_email:
            QMessageBox.information(self, "Kunden-Mail", "Keine gültige Kunden-E-Mail-Adresse vorhanden.")
            return
        subject = self._customer_mail_subject(summary)
        url = f"mailto:{quote(clean_email, safe='@._+-')}?subject={quote(subject, safe='')}"
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "Kunden-Mail", "Das Standard-Mailprogramm konnte nicht geöffnet werden.")

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
        if summary is None:
            self._reset_detail()
            return
        self._populate_detail_for_summary(summary)
        self._prefill_detail_from_invoice_async(summary)

    def _populate_detail_for_summary(self, summary: InvoiceSummary) -> None:
        self._gb_open.hide()
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
        if summary.order_reference:
            self._load_wix_context(summary.order_reference)
        else:
            self._reset_wix_meta("Keine Wix-Order-Referenz")
            self._reset_stuecke()

    def _reset_detail(self) -> None:
        self._gb_open.show()
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
        queued_id = self._queued_invoice_detail_id.strip()
        self._queued_invoice_detail_id = ""
        if not queued_id:
            return
        selected = self._selected_summary()
        if selected is None or queued_id != str(selected.id or "").strip():
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

    def _load_wix_context(self, order_reference: str) -> None:
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
            self._queued_wix_context_ref = ref
            return

        self._wix_context_seq += 1
        seq = self._wix_context_seq
        self._reset_wix_meta("Lade Wix-Daten…")
        self._pending_wix_reference = ref
        self._pending_stuecke_reference = ref
        self._reset_stuecke()
        self._stuecke_hint.setText("Wird geladen…")
        self._gb_stuecke.show()

        def job() -> dict[str, object]:
            wix_client: WixOrdersClient = self._container.resolve(WixOrdersClient)
            if not wix_client.has_credentials():
                return {
                    "seq": seq,
                    "__requested_ref": ref,
                    "status": "Kein Wix-API-Key konfiguriert.",
                    "meta": {},
                    "items": [],
                }

            meta = wix_client.resolve_order_summary(ref)
            wix_items = wix_client.fetch_order_line_items(ref)
            engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
            pieces = engine.get_piece_blocks(wix_items, invoice_ref=ref)
            return {
                "seq": seq,
                "__requested_ref": ref,
                "status": "",
                "meta": meta,
                "items": pieces,
            }

        self._wix_context_worker = BackgroundWorker(job)
        self._wix_context_worker.signals.result.connect(self._on_wix_context_loaded)
        self._wix_context_worker.signals.error.connect(self._on_wix_context_error)
        self._wix_context_worker.signals.finished.connect(self._on_wix_context_finished)
        self._wix_context_worker.start()

    def _on_wix_context_loaded(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        seq = int(data.get("seq") or 0)
        if seq != self._wix_context_seq:
            return
        requested_ref = str(data.get("__requested_ref") or "").strip()
        selected = self._selected_summary()
        current_ref = selected.order_reference.strip() if selected is not None else ""
        if requested_ref and requested_ref != current_ref:
            return

        status = str(data.get("status") or "").strip()
        if status:
            self._put_cached_wix_context(requested_ref, status=status, meta={}, items=[])
            self._wix_order_no.setText(requested_ref or "â€”")
            if not self._current_shipping_lines():
                self._shipping_status.setText(status)
            self._reset_stuecke()
            self._stuecke_hint.setText(status)
            self._stuecke_hint.show()
            self._gb_stuecke.show()
            return

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        self._put_cached_wix_context(requested_ref, status="", meta=meta, items=items)
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
        queued_ref = self._queued_wix_context_ref.strip()
        self._queued_wix_context_ref = ""
        if not queued_ref:
            return
        selected = self._selected_summary()
        current_ref = selected.order_reference.strip() if selected is not None else ""
        if not current_ref or queued_ref != current_ref:
            return
        self._load_wix_context(queued_ref)

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
        self._set_shipping_editor_lines(override_lines or shipping_lines)

    def _on_wix_meta_error(self, exc: Exception) -> None:
        if not self._current_shipping_lines():
            self._shipping_status.setText(f"Wix-Fehler: {exc}")
        logger.warning("Wix meta load failed: %s", exc)

    def _update_plc_controls(self) -> None:
        enabled = self._print_allowed and (self._selected_summary() is not None)
        self._btn_print.setEnabled(enabled)
        self._btn_print_plc.setEnabled(enabled)
        self._btn_print_music.setEnabled(enabled)
        self._btn_print_label.setEnabled(enabled and len(self._current_shipping_lines()) >= 2)
        self._btn_send_invoice.setEnabled(self._selected_summary() is not None)

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
        _ = payload
        self._reload_first_page()
        return
        data = payload if isinstance(payload, dict) else {}
        invoice = str(data.get("invoice") or "—")
        QMessageBox.information(
            self,
            "Labeldruck",
            f"Label für Rechnung {invoice} wurde an den Drucker gesendet.",
        )
        self._reload_first_page()

    def _on_direct_label_print_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Labeldruck",
            f"Label konnte nicht gedruckt werden:\n\n{exc}",
        )

    def _on_direct_invoice_print_result(self, payload: object) -> None:
        _ = payload
        self._reload_first_page()
        return
        data = payload if isinstance(payload, dict) else {}
        invoice = str(data.get("invoice") or "â€”")
        QMessageBox.information(
            self,
            "Rechnungsdruck",
            f"Rechnung {invoice} wurde an den Rechnungsdrucker gesendet.",
        )
        self._reload_first_page()

    def _on_direct_invoice_print_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rechnungsdruck",
            f"Rechnung konnte nicht gedruckt werden:\n\n{exc}",
        )

    def _on_send_invoice_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice = str(data.get("invoice") or "â€”")
        recipient = str(data.get("recipient") or "â€”")
        QMessageBox.information(
            self,
            "Rechnung gesendet",
            f"Rechnung {invoice} wurde an {recipient} gesendet.",
        )
        self._reload_first_page()

    def _on_send_invoice_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rechnung senden",
            f"Rechnung konnte nicht gesendet werden:\n\n{exc}",
        )

    def _on_send_invoice_finished(self) -> None:
        self._invoice_mail_worker = None
        self._overlay.hide()

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
        try:
            service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            preview = service.preview_wix_order_number(reference)
        except Exception as exc:
            dlg.set_preview_result(f"Vorschau fehlgeschlagen:\n{exc}", ok=False)
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
        self._stuecke_hint.setText("—")
        # Remove dynamic item widgets (keep only the hint label)
        while self._stuecke_layout.count() > 1:
            item = self._stuecke_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()
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

        while self._stuecke_layout.count() > 1:
            item = self._stuecke_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()
        self._piece_print_buttons = []
        self._piece_quantity_inputs = []
        self._piece_quantity_controls = []
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
        from xw_studio.ui.modules.rechnungen.print_dialog import prepare_piece_pdf_print

        qty = max(1, int(quantity or self._default_piece_print_qty(block)))
        job = prepare_piece_pdf_print(self, self._container, piece=block, copies=qty)
        if job is None:
            return

        row = self._table.selected_source_row()
        invoice_ref = ""
        if row is not None and 0 <= row < len(self._summaries):
            invoice_ref = self._summaries[row].invoice_number or self._summaries[row].id

        self._set_piece_print_controls_enabled(False)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(f"Produktdruck fuer {block.sku} gestartet ({qty}x).", 5000)

        def worker_job() -> dict[str, object]:
            job()
            try:
                engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
                engine.record_print_and_update_sevdesk(block, qty, invoice_ref=invoice_ref)
            except Exception as exc:
                logger.warning("Stock update after product print failed: %s", exc)
                return {"sku": block.sku, "quantity": qty, "stock_warning": str(exc)}
            return {"sku": block.sku, "quantity": qty, "stock_warning": ""}

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
        signals: AppSignals = self._container.resolve(AppSignals)
        if warning:
            signals.status_message.emit(f"{sku}: {qty}x gedruckt; Bestand nicht aktualisiert.", 8000)
        else:
            signals.status_message.emit(f"{sku}: {qty}x gedruckt und Bestand aktualisiert.", 5000)

    def _on_product_print_error(self, exc: Exception) -> None:
        QMessageBox.critical(
            self,
            "Produktdruck fehlgeschlagen",
            f"Die Produkt-PDF konnte nicht ueber den hinterlegten Druckplan gedruckt werden:\n\n{exc}",
        )

    def _on_product_print_finished(self) -> None:
        self._product_print_worker = None
        self._set_piece_print_controls_enabled(self._print_allowed)

    @staticmethod
    def _default_piece_print_qty(block: PieceBlock) -> int:
        return max(1, int(block.print_qty or block.qty_needed or 1))

    def _set_piece_print_controls_enabled(self, enabled: bool) -> None:
        for button in self._piece_print_buttons:
            button.setEnabled(enabled)
        for qty_input in self._piece_quantity_inputs:
            qty_input.setEnabled(enabled)

    def _on_product_manage_clicked(self, block: PieceBlock) -> None:
        from xw_studio.ui.modules.rechnungen.print_dialog import _configure_missing_piece_print

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
            return [f"Stücke: {block.name}", *parts]
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
