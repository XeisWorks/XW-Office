"""Optional local HTTP ingress for Outlook add-in requests.

Runs a minimal HTTPServer in a BackgroundWorker (QThread) so the UI stays
responsive. The server handles POST /api/xw-copilot, validates HMAC when a
secret is configured and forwards the request to XWCopilotDryRunService.
"""
from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from xw_office.core.worker import BackgroundWorker
from xw_office.services.xw_copilot.security import verify_hmac_signature

if TYPE_CHECKING:
    from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService

logger = logging.getLogger(__name__)

_PATH = "/api/xw-copilot"
_MAX_BODY = 256 * 1024  # 256 KB


class XWCopilotIngressSignals(QObject):
    """Qt signals emitted by XWCopilotIngress for cross-thread communication."""

    request_received = Signal(str, str, bool)  # action, correlation_id, accepted


class XWCopilotIngress:
    """Manages lifecycle of the local ingress HTTP server.

    Usage::

        ingress = XWCopilotIngress(dry_run_service, hmac_secret="â€¦")
        ingress.start(port=8765)
        # later:
        ingress.stop()
    """

    def __init__(self, dry_run_service: "XWCopilotDryRunService", hmac_secret: str = "") -> None:
        self._dry_run = dry_run_service
        self._hmac_secret = hmac_secret
        self._server: HTTPServer | None = None
        self._worker: BackgroundWorker | None = None
        self._port: int | None = None
        self.signals = XWCopilotIngressSignals()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int | None:
        return self._port

    def start(self, port: int = 8765) -> None:
        if self.is_running:
            logger.warning("Ingress already running on port %d", self._port)
            return

        dry_run = self._dry_run
        secret = self._hmac_secret
        signals = self.signals
        get_config = self._dry_run._config_service.load_config

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
                logger.debug("Ingress: " + fmt, *args)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != _PATH:
                    self.send_error(404, "Not found")
                    return

                    # IP-allowlist check (skip when list is empty)
                    allowed_ips_raw = get_config().allowed_ips.strip()
                    if allowed_ips_raw:
                        allowed = {ip.strip() for ip in allowed_ips_raw.split(",") if ip.strip()}
                        client_ip = self.client_address[0]
                        if client_ip not in allowed:
                            logger.warning("Ingress: rejected request from %s (not in allowlist)", client_ip)
                            self.send_error(403, "Forbidden")
                            return

                length = int(self.headers.get("Content-Length") or 0)
                if length > _MAX_BODY:
                    self.send_error(413, "Payload too large")
                    return

                body = self.rfile.read(length)

                # HMAC check (skip if no secret configured)
                if secret:
                    sig = self.headers.get("X-XW-Signature", "")
                    if not verify_hmac_signature(body, sig, secret):
                        self.send_error(401, "Invalid signature")
                        return

                result = dry_run.simulate_raw_request(body.decode("utf-8", errors="replace"))
                response_json = result.model_dump_json().encode("utf-8")
                self.send_response(200 if result.accepted else 422)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_json)))
                self.end_headers()
                self.wfile.write(response_json)
                # Emit cross-thread signal so UI can auto-refresh history
                signals.request_received.emit(result.action, result.correlation_id, result.accepted)

        server = HTTPServer(("127.0.0.1", port), _Handler)
        self._server = server
        self._port = port

        def _serve() -> None:
            logger.info("XW-Copilot ingress listening on 127.0.0.1:%d", port)
            server.serve_forever()

        worker = BackgroundWorker(_serve)
        worker.signals.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()
        logger.info("Ingress worker started")

    def stop(self) -> None:
        if self._server is None:
            return
        logger.info("Stopping XW-Copilot ingress")
        self._server.shutdown()
        # _on_worker_finished clears state once QThread exits

    def update_secret(self, hmac_secret: str) -> None:
        self._hmac_secret = hmac_secret

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_worker_finished(self) -> None:
        if self._server is not None:
            self._server.server_close()
        self._server = None
        self._worker = None
        self._port = None
        logger.info("XW-Copilot ingress stopped")
