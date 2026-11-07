"""Optional Playwright runtime for visible, persistent account sessions.

This module contains browser lifecycle and profile isolation only.  Provider adapters supply
tested page callbacks; no selectors or private endpoints are invented here.
"""
from __future__ import annotations

from pathlib import Path
import os
from threading import Lock
from typing import Any, Callable
from urllib.parse import urlparse

from xw_office.services.invoice_collection.domain import DocumentCandidate
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.security import assert_local_path


PageCallback = Callable[[Any], Any]


class PlaywrightPersistentSession:
    """Headful persistent session; caller remains responsible for real DOM callbacks."""

    def __init__(
        self,
        *,
        profile_dir: Path,
        login_url: str,
        probe_url: str,
        allowed_hosts: frozenset[str],
        probe_callback: PageCallback,
        discover_callback: PageCallback,
        download_callback: Callable[[Any, DocumentCandidate, Path], None],
        timeout_ms: int = 30_000,
    ) -> None:
        assert_local_path(profile_dir)
        self.profile_dir = profile_dir
        self.login_url = login_url
        self.probe_url = probe_url
        self.allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)
        self.probe_callback = probe_callback
        self.discover_callback = discover_callback
        self.download_callback = download_callback
        self.timeout_ms = timeout_ms
        self._playwright: Any = None
        self._context: Any = None
        self._profile_lock: Any = None
        self._lock = Lock()

    def _ensure_started(self) -> Any:
        with self._lock:
            if self._context is not None:
                return self._context
            self._validate_url(self.login_url)
            self._validate_url(self.probe_url)
            lock_path = self.profile_dir.with_name(f"{self.profile_dir.name}.lock")
            self.profile_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._profile_lock = open(lock_path, "x", encoding="utf-8")
            except FileExistsError as exc:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.POLICY_BLOCKED,
                    "Browserprofil wird bereits von einem anderen Abruf verwendet",
                ) from exc
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                self.close()
                raise InvoiceCollectionError(
                    InvoiceErrorCode.CONFIGURATION_ERROR,
                    "Playwright ist für diese Browserroute nicht installiert",
                ) from exc
            self._playwright = sync_playwright().start()
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=False,
                    accept_downloads=True,
                )
            except Exception:
                self.close()
                raise
            return self._context

    def probe(self) -> bool:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(self.probe_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        return bool(self.probe_callback(page))

    def open_login(self) -> None:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=self.timeout_ms)

    def discover(self) -> list[DocumentCandidate]:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(self.probe_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        result = self.discover_callback(page)
        return list(result or ())

    def download(self, candidate: DocumentCandidate, destination: Path) -> None:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        self.download_callback(page, candidate, destination)

    def close(self) -> None:
        context, playwright, profile_lock = self._context, self._playwright, self._profile_lock
        self._context = None
        self._playwright = None
        self._profile_lock = None
        try:
            if context is not None:
                context.close()
        finally:
            try:
                if playwright is not None:
                    playwright.stop()
            finally:
                if profile_lock is not None:
                    lock_path = self.profile_dir.with_name(f"{self.profile_dir.name}.lock")
                    profile_lock.close()
                    lock_path.unlink(missing_ok=True)

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() not in self.allowed_hosts:
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED,
                "Browserroute verwendet einen nicht erlaubten HTTPS-Host",
            )
