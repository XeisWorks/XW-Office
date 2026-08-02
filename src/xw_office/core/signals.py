"""Application-wide signal bus for cross-module communication."""
from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """Singleton signal bus. Resolve via container.resolve(AppSignals)."""

    navigate_to_module = Signal(str)
    show_home = Signal()

    invoices_changed = Signal()
    inventory_changed = Signal()
    customers_changed = Signal()

    status_message = Signal(str, int)
    task_started = Signal(str)
    task_progress = Signal(str, int)
    task_finished = Signal(str)
    task_error = Signal(str, str)

    print_job_queued = Signal(str)
    print_job_completed = Signal(str)

    show_toast = Signal(str, str)

    printer_status_changed = Signal(bool)
    badge_updated = Signal(str, int)

    theme_changed = Signal(str)
