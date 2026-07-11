"""Main application window with sidebar navigation and lazy module loading."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.printer_status.service import PrinterStatusService, PrinterStatusSnapshot
from xw_studio.ui.sidebar import Sidebar
from xw_studio.ui.status_bar import StudioStatusBar
from xw_studio.ui.theme import apply_app_theme

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """XeisWorks Studio main window: sidebar + content area."""

    def __init__(self, container: Container) -> None:
        super().__init__()
        self._container = container
        self._pages: dict[str, QWidget] = {}
        self._page_factories: dict[str, Callable[[], QWidget]] = {}
        self._loading_pages: set[str] = set()
        self._startup_preload_worker: BackgroundWorker | None = None
        self._printer_status_worker: BackgroundWorker | None = None
        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._open_initial_module()
        self._apply_printer_status()
        self._refresh_printer_status_async()

    def _setup_window(self) -> None:
        cfg = self._container.config.app.window
        self.setWindowTitle(self._container.config.app.name)
        self.resize(cfg.width, cfg.height)
        self.setMinimumSize(1024, 700)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = Sidebar(self._container)
        self._sidebar.module_selected.connect(self._navigate_to)
        layout.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        self._status_bar = StudioStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Bereit", 5000)

        from xw_studio.ui.home_view import HomeView

        self._register_page(ModuleKey.HOME, HomeView(self._container))
        self._register_lazy_pages()
        self._stack.setCurrentWidget(self._pages[ModuleKey.HOME.value])

    def _connect_signals(self) -> None:
        signals = self._container.resolve(AppSignals)
        signals.navigate_to_module.connect(self._navigate_to)
        signals.show_home.connect(lambda: self._navigate_to(ModuleKey.HOME.value))
        signals.status_message.connect(self._status_bar.showMessage)
        signals.theme_changed.connect(self._apply_theme)

    def _open_initial_module(self) -> None:
        signals = self._container.resolve(AppSignals)
        # Keep first paint responsive, then preload Rechnungen in background.
        signals.navigate_to_module.emit(ModuleKey.HOME.value)
        self._start_startup_preload()

    def _start_startup_preload(self) -> None:
        if self._startup_preload_worker is not None and self._startup_preload_worker.isRunning():
            return

        def job() -> tuple[int, int]:
            from xw_studio.services.secrets.service import SecretService
            from xw_studio.services.invoice_processing.service import InvoiceProcessingService

            secret_service = self._container.resolve(SecretService)
            preload_secrets = getattr(secret_service, "preload", None)
            if callable(preload_secrets):
                preload_secrets()
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            warm = getattr(service, "warm_startup_batches", None)
            if callable(warm):
                return warm(draft_limit=5, open_limit=5)
            return (0, 0)

        self._startup_preload_worker = BackgroundWorker(job)
        self._startup_preload_worker.signals.result.connect(self._on_startup_preload_result)
        self._startup_preload_worker.signals.error.connect(self._on_startup_preload_error)
        self._startup_preload_worker.signals.finished.connect(lambda: setattr(self, "_startup_preload_worker", None))
        self._startup_preload_worker.start()

    def _on_startup_preload_result(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        draft_count = max(0, int(payload[0]))
        open_count = max(0, int(payload[1]))
        self._status_bar.showMessage(
            f"Rechnungen vorab geladen: {draft_count} Entwuerfe, {open_count} offen",
            4000,
        )

    def _on_startup_preload_error(self, exc: Exception) -> None:
        logger.debug("Startup invoice preload skipped/failed: %s", exc)

    def _apply_theme(self, theme_name: str) -> None:
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                apply_app_theme(app, theme_name)
                logger.info("Theme switched to %s", theme_name)
        except Exception as exc:
            logger.warning("Theme switch failed: %s", exc)

    def _apply_printer_status(self) -> None:
        service: PrinterStatusService = self._container.resolve(PrinterStatusService)
        self._apply_printer_status_snapshot(service.snapshot())

    def _apply_printer_status_snapshot(self, snapshot: PrinterStatusSnapshot) -> None:
        self._status_bar.set_printer_status(snapshot.color, snapshot.tooltip)
        signals = self._container.resolve(AppSignals)
        signals.printer_status_changed.emit(snapshot.printing_allowed)

    def _refresh_printer_status_async(self) -> None:
        if self._printer_status_worker is not None and self._printer_status_worker.isRunning():
            return

        def job() -> PrinterStatusSnapshot:
            service: PrinterStatusService = self._container.resolve(PrinterStatusService)
            return service.refresh(force=True)

        self._printer_status_worker = BackgroundWorker(job)
        self._printer_status_worker.signals.result.connect(self._on_printer_status_result)
        self._printer_status_worker.signals.error.connect(self._on_printer_status_error)
        self._printer_status_worker.signals.finished.connect(lambda: setattr(self, "_printer_status_worker", None))
        self._printer_status_worker.start()

    def _on_printer_status_result(self, payload: object) -> None:
        if isinstance(payload, PrinterStatusSnapshot):
            self._apply_printer_status_snapshot(payload)

    def _on_printer_status_error(self, exc: Exception) -> None:
        logger.debug("Printer status refresh failed: %s", exc)

    def _register_page(self, key: str | ModuleKey, widget: QWidget) -> None:
        key_str = key.value if isinstance(key, ModuleKey) else key
        self._pages[key_str] = widget
        self._stack.addWidget(widget)

    def _register_page_factory(self, key: str | ModuleKey, factory: Callable[[], QWidget]) -> None:
        key_str = key.value if isinstance(key, ModuleKey) else key
        self._page_factories[key_str] = factory

    def _register_lazy_pages(self) -> None:
        self._register_page_factory(ModuleKey.RECHNUNGEN, self._build_rechnungen_page)
        self._register_page_factory(ModuleKey.GUTSCHEINE, self._build_gutscheine_page)
        self._register_page_factory(ModuleKey.MOLLIE, self._build_mollie_page)
        self._register_page_factory(ModuleKey.PRODUCTS, self._build_products_page)
        self._register_page_factory(ModuleKey.CRM, self._build_crm_page)
        self._register_page_factory(ModuleKey.TAXES, self._build_taxes_page)
        self._register_page_factory(ModuleKey.CLEARING, self._build_clearing_page)
        self._register_page_factory(ModuleKey.STATISTICS, self._build_statistics_page)
        self._register_page_factory(ModuleKey.CALCULATION, self._build_calculation_page)
        self._register_page_factory(ModuleKey.LAYOUT, self._build_layout_page)
        self._register_page_factory(ModuleKey.WUEDARAMUSI, self._build_wuedaramusi_page)
        self._register_page_factory(ModuleKey.TRAVEL_COSTS, self._build_travel_costs_page)
        self._register_page_factory(ModuleKey.MARKETING, self._build_marketing_page)
        self._register_page_factory(ModuleKey.NOTATION, self._build_notation_page)
        self._register_page_factory(ModuleKey.XW_COPILOT, self._build_xw_copilot_page)
        self._register_page_factory(ModuleKey.SETTINGS, self._build_settings_page)

    def _navigate_to(self, module_key: str) -> None:
        if module_key in self._page_factories and module_key not in self._pages:
            placeholder = self._create_placeholder(module_key)
            self._register_page(module_key, placeholder)
            self._stack.setCurrentWidget(placeholder)
            self._build_page_async(module_key, placeholder)
            logger.debug("Navigated to %s (placeholder)", module_key)
            return
        if module_key in self._pages:
            self._stack.setCurrentWidget(self._pages[module_key])
            logger.debug("Navigated to %s", module_key)
            return

        placeholder = self._create_placeholder(module_key)
        self._register_page(module_key, placeholder)
        self._stack.setCurrentWidget(placeholder)

    def _build_page_async(self, module_key: str, placeholder: QWidget) -> None:
        if module_key in self._loading_pages:
            return
        factory = self._page_factories.get(module_key)
        if factory is None:
            return
        self._loading_pages.add(module_key)

        def materialize() -> None:
            try:
                widget = factory()
                self._pages[module_key] = widget
                self._stack.addWidget(widget)
                if self._stack.currentWidget() is placeholder:
                    self._stack.setCurrentWidget(widget)
                self._stack.removeWidget(placeholder)
                placeholder.deleteLater()
            except Exception:
                logger.exception("Failed to build module page: %s", module_key)
            finally:
                self._loading_pages.discard(module_key)

        QTimer.singleShot(0, materialize)

    def page(self, module_key: str | ModuleKey) -> QWidget | None:
        """Return a materialized page, excluding temporary loading shells."""
        key = module_key.value if isinstance(module_key, ModuleKey) else module_key
        if key in self._loading_pages:
            return None
        return self._pages.get(key)

    def _create_placeholder(self, module_key: str) -> QWidget:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(f"Modul '{module_key}' wird geladen...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 18px; color: #888;")
        layout.addWidget(label)
        return page

    def _build_rechnungen_page(self) -> QWidget:
        from xw_studio.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView

        return TagesgeschaeftView(self._container)

    def _build_gutscheine_page(self) -> QWidget:
        from xw_studio.ui.modules.gutscheine.view import GutscheineView

        return GutscheineView(self._container)

    def _build_mollie_page(self) -> QWidget:
        from xw_studio.ui.modules.mollie.view import MollieView

        return MollieView(self._container)

    def _build_products_page(self) -> QWidget:
        from xw_studio.ui.modules.products.view import ProductsView

        return ProductsView(self._container)

    def _build_crm_page(self) -> QWidget:
        from xw_studio.ui.modules.crm.view import CrmView

        return CrmView(self._container)

    def _build_taxes_page(self) -> QWidget:
        from xw_studio.ui.modules.taxes.view import TaxesView

        return TaxesView(self._container)

    def _build_clearing_page(self) -> QWidget:
        from xw_studio.ui.modules.payment_clearing.view import PaymentClearingView

        return PaymentClearingView(self._container)

    def _build_statistics_page(self) -> QWidget:
        from xw_studio.ui.modules.statistics.view import StatisticsView

        return StatisticsView(self._container)

    def _build_calculation_page(self) -> QWidget:
        from xw_studio.ui.modules.calculation.view import CalculationView

        return CalculationView(self._container)

    def _build_layout_page(self) -> QWidget:
        from xw_studio.ui.modules.layout.view import LayoutView

        return LayoutView(self._container)

    def _build_wuedaramusi_page(self) -> QWidget:
        from xw_studio.ui.modules.wuedaramusi.view import WuedaraMusiView

        return WuedaraMusiView(self._container)

    def _build_travel_costs_page(self) -> QWidget:
        from xw_studio.ui.modules.travel_costs.view import TravelCostsView

        return TravelCostsView(self._container)

    def _build_marketing_page(self) -> QWidget:
        from xw_studio.ui.modules.marketing.view import MarketingView

        return MarketingView(self._container)

    def _build_notation_page(self) -> QWidget:
        from xw_studio.ui.modules.notation.view import NotationView

        return NotationView(self._container)

    def _build_xw_copilot_page(self) -> QWidget:
        from xw_studio.ui.modules.xw_copilot.view import XWCopilotView

        return XWCopilotView(self._container)

    def _build_settings_page(self) -> QWidget:
        from xw_studio.ui.modules.settings.view import SettingsView

        return SettingsView(self._container)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._startup_preload_worker is not None and self._startup_preload_worker.isRunning():
            self._startup_preload_worker.wait(2000)
        for widget in self._pages.values():
            has_active_flow = getattr(widget, "has_active_flow", None)
            if callable(has_active_flow) and has_active_flow():
                QMessageBox.warning(
                    self,
                    "App beenden",
                    "Es laeuft noch ein Workflow. Bitte zuerst STOP bzw. den laufenden Flow abschliessen.",
                )
                event.ignore()
                return
        for widget in self._pages.values():
            prepare_shutdown = getattr(widget, "prepare_shutdown", None)
            if callable(prepare_shutdown):
                prepare_shutdown()
        super().closeEvent(event)
