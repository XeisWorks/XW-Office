"""Application factory: config, DI, theme, main window."""
from __future__ import annotations

import logging
import os
import platform
import sys

from sqlalchemy import text
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from xw_office.bootstrap import register_default_services
from xw_office.core.app_paths import app_icon_path, ensure_app_user_model_id
from xw_office.core.config import AppConfig, load_config
from xw_office.core.container import Container
from xw_office.core.database import create_engine_from_config, ensure_core_tables
from xw_office.core.logging_setup import (
    install_qt_message_handler,
    log_startup_info,
    setup_logging,
)
from xw_office.core.signals import AppSignals
from xw_office.core.updater import check_and_update
from xw_office.core.printer_detect import discover_printers
from xw_office.repositories import PcRegistryRepository
from xw_office.ui.theme import apply_app_theme

logger = logging.getLogger(__name__)

APP_VERSION = "0.1.0"


def _retain_main_window(app: QApplication, window: object) -> None:
    """Keep the Python wrapper for the top-level window alive with the app.

    Qt does not parent top-level windows to ``QApplication``.  Without an
    explicit Python reference, signal cycles can be garbage-collected while
    child ``QThread`` instances are still running, which makes Qt abort the
    process with ``QThread: Destroyed while thread is still running``.
    """
    app._xw_main_window = window  # type: ignore[attr-defined]


def _check_database_connection(config: AppConfig) -> str | None:
    """Return an error string when DB ping fails, else ``None``."""
    if not (config.database_url or "").strip():
        return None
    engine = None
    try:
        engine = create_engine_from_config(config)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        created_tables = ensure_core_tables(engine)
        if created_tables:
            logger.warning(
                "Database missing core tables. Created automatically: %s",
                ", ".join(created_tables),
            )
        return None
    except Exception as exc:
        return str(exc)
    finally:
        if engine is not None:
            engine.dispose()


def _handle_exception(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
    """Global exception handler — log and show dialog."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    QMessageBox.critical(
        None,
        "Unerwarteter Fehler",
        f"Ein unerwarteter Fehler ist aufgetreten:\n\n{exc_value}\n\n"
        "Bitte die Log-Datei pruefen.",
    )


def _register_workstation(container: Container) -> None:
    if not (container.config.database_url or "").strip():
        return
    try:
        configured_printers = {
            str(name).strip()
            for name in container.config.printing.configured_printer_names
            if str(name).strip()
        }
        available_printers = {printer.name for printer in discover_printers()}
        machine_id = str(os.getenv("COMPUTERNAME") or platform.node() or "unknown").strip()
        container.resolve(PcRegistryRepository).upsert_last_seen(
            machine_id,
            display_name=machine_id,
            is_print_station=bool(configured_printers.intersection(available_printers)),
        )
    except Exception as exc:
        logger.warning("Workstation registry update failed: %s", exc)


def create_application() -> QApplication:
    """Build and return the fully wired QApplication."""
    ensure_app_user_model_id()

    setup_logging()
    install_qt_message_handler()
    start_mode = os.getenv("XW_OFFICE_START_MODE") or ("gui" if sys.stdout is None else "console")
    log_startup_info(start_mode, APP_VERSION)
    logger.info("Starting XeisWorks Office...")

    update_result = check_and_update(enabled=False)
    if update_result.updated:
        logger.info("Code updated from remote. Restart recommended.")

    config = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName(config.app.name)
    app.setApplicationVersion(APP_VERSION)

    icon_path = app_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_app_theme(app, config.app.theme)

    sys.excepthook = _handle_exception

    container = Container(config)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)

    db_error = _check_database_connection(config)
    if db_error:
        logger.warning("Database connectivity check failed: %s", db_error)
        QMessageBox.warning(
            None,
            "Datenbank",
            "PostgreSQL-Verbindung fehlgeschlagen. Die App startet trotzdem, "
            "aber DB-gestuetzte Funktionen sind eingeschraenkt.\n\n"
            f"Fehler: {db_error}",
        )
    else:
        _register_workstation(container)

    from xw_office.ui.main_window import MainWindow
    window = MainWindow(container)
    _retain_main_window(app, window)
    window.showMaximized()

    return app
