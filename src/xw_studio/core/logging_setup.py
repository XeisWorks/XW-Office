"""Centralized logging configuration."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _configure_noisy_dependency_loggers() -> None:
    """Clamp third-party logger verbosity unless explicitly overridden."""
    configured = str(os.getenv("XW_STUDIO_HTTP_LOG_LEVEL", "WARNING")).strip().upper()
    level = getattr(logging, configured, logging.WARNING)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(level)


def setup_logging(level: int = logging.INFO, log_dir: Path | None = None) -> None:
    """Configure root logger with console + optional rotating file handler."""
    root = logging.getLogger()
    root.setLevel(level)

    _configure_noisy_dependency_loggers()

    if root.handlers:
        return

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "xw_studio.log",
            maxBytes=2 * 1024 * 1024,  # 2 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
