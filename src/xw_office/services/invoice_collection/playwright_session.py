"""Optional Playwright runtime for visible, persistent account sessions.

This module contains browser lifecycle and profile isolation only.  Provider adapters supply
tested page callbacks; no selectors or private endpoints are invented here.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import socket
import subprocess
from threading import Lock
import time
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import urlopen

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
        playwright_factory: Callable[[], Any] | None = None,
        browser_mode: str = "playwright_chromium",
        chrome_executable: Path | None = None,
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
        self._playwright_factory = playwright_factory
        self.browser_mode = browser_mode
        self.chrome_executable = chrome_executable
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._profile_lock: Any = None
        self._chrome_process: subprocess.Popen[bytes] | None = None
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
                if self._playwright_factory is None:
                    try:
                        from playwright.sync_api import sync_playwright
                    except ImportError as exc:
                        raise InvoiceCollectionError(
                            InvoiceErrorCode.CONFIGURATION_ERROR,
                            "Playwright ist für diese Browserroute nicht installiert",
                        ) from exc
                    self._playwright = sync_playwright().start()
                else:
                    self._playwright = self._playwright_factory().start()
                if self.browser_mode in {
                    "system_chrome_cdp",
                    "system_chrome_existing_profile",
                }:
                    self._context = self._connect_system_chrome()
                elif self.browser_mode == "playwright_chromium":
                    self._context = self._playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=False,
                        accept_downloads=True,
                    )
                else:
                    raise InvoiceCollectionError(
                        InvoiceErrorCode.CONFIGURATION_ERROR,
                        "Unbekannter Playwright-Browsermodus",
                    )
            except Exception:
                # Every failed startup must release both the profile lock and runtime.
                self.close()
                raise
            return self._context

    def _connect_system_chrome(self) -> Any:
        executable = self.chrome_executable or _find_system_chrome()
        if executable is None:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONFIGURATION_ERROR,
                "Installiertes Google Chrome wurde nicht gefunden",
            )
        if self.browser_mode == "system_chrome_existing_profile" and (
            self.profile_dir / "SingletonLock"
        ).exists():
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED,
                "Alle normalen Google-Chrome-Fenster mÃ¼ssen vor der ProfilÃ¼bernahme geschlossen werden",
            )
        if self.browser_mode == "system_chrome_existing_profile" and _chrome_process_running():
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED,
                "Normale Google-Chrome-Prozesse laufen noch; ProfilÃ¼bernahme wurde nicht gestartet",
            )
        port = _free_local_port()
        command = [
            str(executable),
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self.browser_mode == "system_chrome_existing_profile":
            command.append("--profile-directory=Default")
        command.append(self.login_url)
        self._chrome_process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        endpoint = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + min(15.0, self.timeout_ms / 1000)
        while time.monotonic() < deadline:
            if self._chrome_process.poll() is not None:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.INTERNAL_ERROR,
                    "Google Chrome konnte nicht gestartet werden",
                )
            try:
                with urlopen(f"{endpoint}/json/version", timeout=1.0):
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise InvoiceCollectionError(
                InvoiceErrorCode.TRANSIENT_NETWORK,
                "Google Chrome Remote-Debugging wurde nicht erreichbar",
            )
        self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        if not self._browser.contexts:
            raise InvoiceCollectionError(
                InvoiceErrorCode.INTERNAL_ERROR,
                "Google Chrome liefert keinen Browserkontext",
            )
        return self._browser.contexts[0]

    def probe(self) -> bool:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        self._run_portal_action(
            page.goto,
            self.probe_url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        return bool(self._run_portal_action(self.probe_callback, page))

    def open_login(self) -> None:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        self._run_portal_action(
            page.goto,
            self.login_url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )

    def discover(self) -> list[DocumentCandidate]:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        self._run_portal_action(
            page.goto,
            self.probe_url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        result = self._run_portal_action(self.discover_callback, page)
        return list(result or ())

    def download(self, candidate: DocumentCandidate, destination: Path) -> None:
        context = self._ensure_started()
        page = context.pages[0] if context.pages else context.new_page()
        self._run_portal_action(self.download_callback, page, candidate, destination)

    @staticmethod
    def _run_portal_action(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return callback(*args, **kwargs)
        except InvoiceCollectionError as exc:
            safe_messages = {
                InvoiceErrorCode.AUTH_REQUIRED: "Browserroute benötigt eine Anmeldung",
                InvoiceErrorCode.POLICY_BLOCKED: "Browserroute wurde durch eine Richtlinie blockiert",
            }
            message = safe_messages.get(exc.code, "Browserroute meldet einen Fehler")
            raise InvoiceCollectionError(exc.code, message) from exc
        except Exception as exc:  # noqa: BLE001 - vendor DOM errors vary by Playwright version
            if "timeout" in type(exc).__name__.casefold():
                raise InvoiceCollectionError(
                    InvoiceErrorCode.TRANSIENT_NETWORK,
                    "Browserroute hat das Zeitlimit überschritten",
                ) from exc
            raise InvoiceCollectionError(
                InvoiceErrorCode.PROVIDER_CHANGED,
                "Browserroute konnte die erwartete Seite nicht verarbeiten",
            ) from exc

    @staticmethod
    def save_download(page: Any, trigger: Callable[[], None], destination: Path) -> None:
        """Persist a real Playwright download without reconstructing cookie headers."""
        with page.expect_download() as download_info:
            trigger()
        download_info.value.save_as(str(destination))

    def close(self) -> None:
        context, browser, playwright, profile_lock = (
            self._context,
            self._browser,
            self._playwright,
            self._profile_lock,
        )
        self._context = None
        self._browser = None
        self._playwright = None
        self._profile_lock = None
        chrome_alive = self._chrome_process is not None and self._chrome_process.poll() is None
        try:
            if context is not None and self.browser_mode not in {"system_chrome_cdp", "system_chrome_existing_profile"}:
                context.close()
        finally:
            try:
                if browser is not None and chrome_alive:
                    try:
                        browser.close()
                    except Exception:
                        # The owned Chrome process may already have exited after
                        # the user closed its visible window.
                        pass
            finally:
                try:
                    if self._chrome_process is not None:
                        self._chrome_process.terminate()
                        self._chrome_process.wait(timeout=5)
                except Exception:
                    if self._chrome_process is not None:
                        self._chrome_process.kill()
                finally:
                    self._chrome_process = None
                try:
                    if playwright is not None:
                        try:
                            playwright.stop()
                        except Exception:
                            pass
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


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _find_system_chrome() -> Path | None:
    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(shutil.which("chrome.exe") or ""),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _chrome_process_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return "chrome.exe" in result.stdout.casefold()
