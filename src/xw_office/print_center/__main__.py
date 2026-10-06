"""Standalone entry point: no Office main window, sync or external write services."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from xw_office.app import _handle_exception, _retain_main_window
from xw_office.core.app_paths import ensure_app_user_model_id
from xw_office.core.config import load_config
from xw_office.core.container import Container
from xw_office.core.database import create_session_factory
from xw_office.core.logging_setup import install_qt_message_handler, setup_logging
from xw_office.print_center.official import OfficialCatalogue
from xw_office.print_center.icons import printer_icon
from xw_office.print_center.repository import OwnArticleRepository
from xw_office.print_center.service import PrintCenterService
from xw_office.print_center.window import PrintCenterWindow
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.ui.theme import apply_app_theme

logger = logging.getLogger(__name__)


def create_print_center_application() -> QApplication:
    ensure_app_user_model_id("at.xeisworks.printcenter")
    setup_logging()
    install_qt_message_handler()
    config = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName("XeisWorks Druckcenter")
    app.setApplicationDisplayName("XeisWorks Druckcenter")
    app.setWindowIcon(printer_icon())
    apply_app_theme(app, config.app.theme)
    sys.excepthook = _handle_exception
    database_url = os.getenv("XW_PRINT_CENTER_DATABASE_URL", "").strip()
    sessions = create_session_factory(
        replace(config, database_url=database_url) if database_url else config
    )
    container = Container(config)
    container.register(
        OfficialCatalogue,
        lambda _: OfficialCatalogue(sessions, prefer_hub=config.product_hub.catalog_read_enabled),
    )
    container.register(OwnArticleRepository, lambda _: OwnArticleRepository(sessions))
    container.register(PrintQueueService, lambda _: PrintQueueService())
    container.register(
        PrintCenterService,
        lambda c: PrintCenterService(
            c.resolve(OfficialCatalogue), c.resolve(OwnArticleRepository),
            lambda: load_config().printing, c.resolve(PrintQueueService),
        ),
    )
    window = PrintCenterWindow(container.resolve(PrintCenterService))
    window.setWindowIcon(printer_icon())
    _retain_main_window(app, window)
    window.show()
    logger.info("Standalone print center started; Office synchronization is not initialized.")
    return app


def main() -> None:
    app = create_print_center_application()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
