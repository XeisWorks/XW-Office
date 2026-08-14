"""Centralized logging configuration."""
from __future__ import annotations

import faulthandler
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from xw_office.core.app_paths import crash_log_file_path, find_repo_root

logger = logging.getLogger(__name__)

# Kept alive for the process lifetime so faulthandler can keep writing to it.
_crash_file: object | None = None

_SECRET_PATTERN = re.compile(
    r"(?i)\b(authorization|api[_-]?token|api[_-]?key|password|secret|pin|bearer)\b"
    r"(\s*[:=]\s*)([^\s,;\"']{3,})"
)


class _SecretRedactionFilter(logging.Filter):
    """Redact obvious secret-bearing key/value pairs before they reach a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _SECRET_PATTERN.sub(r"\1\2***redacted***", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def _configure_noisy_dependency_loggers() -> None:
    """Clamp third-party logger verbosity unless explicitly overridden."""
    configured = str(os.getenv("XW_OFFICE_HTTP_LOG_LEVEL", "WARNING")).strip().upper()
    level = getattr(logging, configured, logging.WARNING)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(level)


def _resolve_level(env_var: str, default: int) -> int:
    configured = str(os.getenv(env_var, "")).strip().upper()
    resolved = getattr(logging, configured, None)
    return resolved if isinstance(resolved, int) else default


def _has_usable_stream(stream: object) -> bool:
    """``sys.stdout``/``sys.stderr`` can be ``None`` (or a closed stub) under pythonw.exe."""
    return stream is not None and hasattr(stream, "write") and hasattr(stream, "flush")


def _enable_crash_dumps(log_dir: Path) -> None:
    global _crash_file
    if _crash_file is not None:
        return
    try:
        crash_file = open(crash_log_file_path(), "a", encoding="utf-8")
    except OSError:
        logger.warning("Could not open crash log under %s", log_dir)
        return
    _crash_file = crash_file
    faulthandler.enable(file=crash_file)


def setup_logging(level: int | None = None, log_dir: Path | None = None) -> None:
    """Configure the root logger with a file handler and, when possible, a console handler.

    The file handler is always active and anchored to the repo root, independent of the
    current working directory. A console handler is only added when a real, writable
    stdout stream exists (it does not under ``pythonw.exe``, where ``sys.stdout`` is ``None``).
    """
    root = logging.getLogger()
    if root.handlers:
        return

    resolved_level = level if level is not None else _resolve_level("XW_OFFICE_LOG_LEVEL", logging.INFO)
    root.setLevel(resolved_level)

    _configure_noisy_dependency_loggers()
    logging.captureWarnings(True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redaction_filter = _SecretRedactionFilter()

    if log_dir is None:
        log_dir = find_repo_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    max_bytes = int(os.getenv("XW_OFFICE_LOG_MAX_BYTES", str(8 * 1024 * 1024)))
    backup_count = int(os.getenv("XW_OFFICE_LOG_BACKUP_COUNT", "8"))
    file_handler = RotatingFileHandler(
        log_dir / "xw_office.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(resolved_level)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(redaction_filter)
    root.addHandler(file_handler)

    if _has_usable_stream(sys.stdout):
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(resolved_level)
        console.setFormatter(fmt)
        console.addFilter(redaction_filter)
        root.addHandler(console)

    _enable_crash_dumps(log_dir)


def install_qt_message_handler() -> None:
    """Route Qt's own log/warning/critical/fatal messages into the ``logging`` module."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    qt_logger = logging.getLogger("xw_office.qt")
    level_map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _handler(msg_type: QtMsgType, context: object, message: str) -> None:
        qt_logger.log(level_map.get(msg_type, logging.INFO), message)

    qInstallMessageHandler(_handler)


def log_startup_info(start_mode: str, app_version: str) -> None:
    """Log a compact block of facts that make a support/diagnosis session self-contained."""
    import platform
    import subprocess

    from xw_office.core.app_paths import find_repo_root, log_file_path

    repo_root = find_repo_root()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"

    logger.info(
        "Startup info: version=%s mode=%s pid=%s computer=%s interpreter=%s repo=%s commit=%s log=%s",
        app_version,
        start_mode,
        os.getpid(),
        os.getenv("COMPUTERNAME") or platform.node() or "unknown",
        sys.executable,
        repo_root,
        commit,
        log_file_path(),
    )
