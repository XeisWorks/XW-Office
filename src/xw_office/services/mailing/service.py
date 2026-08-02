"""Microsoft Graph-backed mail delivery for invoice/customer messages."""
from __future__ import annotations

from dataclasses import dataclass
import html
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING

from xw_office.services.mailing.graph_client import GraphMailClient, default_graph_cache_path

if TYPE_CHECKING:
    from xw_office.services.secrets.service import SecretService


@dataclass(frozen=True)
class MailAttachment:
    """One binary attachment for a mail message."""

    filename: str
    content: bytes
    mime_type: str = "application/pdf"


@dataclass(frozen=True)
class GraphMailConfig:
    """Resolved Graph mail configuration from DB/env secrets."""

    tenant_id: str
    client_id: str
    mailbox_user: str
    cache_path: Path


class MailDeliveryService:
    """Render and send customer mails via Microsoft Graph only."""

    def __init__(self, *, secret_service: "SecretService | None" = None) -> None:
        self._secrets = secret_service
        self._client: GraphMailClient | None = None
        self._client_key: tuple[str, str, str, str] | None = None

    def is_configured(self) -> bool:
        try:
            self.load_graph_config()
        except RuntimeError:
            return False
        return True

    def load_graph_config(self) -> GraphMailConfig:
        tenant_id = self._secret_or_env("MS_GRAPH_TENANT_ID")
        client_id = self._secret_or_env("MS_GRAPH_CLIENT_ID")
        mailbox_user = self._secret_or_env("MS_GRAPH_MAILBOX")
        cache_override = self._secret_or_env("XW_OFFICE_MSAL_CACHE_PATH") or self._secret_or_env(
            "SEVDESK_MSAL_CACHE_PATH"
        )

        missing = [
            name
            for name, value in (
                ("MS_GRAPH_TENANT_ID", tenant_id),
                ("MS_GRAPH_CLIENT_ID", client_id),
                ("MS_GRAPH_MAILBOX", mailbox_user),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"MS-Graph-Konfiguration fehlt: {', '.join(missing)}")

        cache_path = default_graph_cache_path()
        if cache_override:
            raw_path = Path(os.path.expandvars(os.path.expanduser(cache_override)))
            cache_path = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path

        return GraphMailConfig(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_user=mailbox_user,
            cache_path=cache_path,
        )

    def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str = "",
        attachments: list[MailAttachment] | None = None,
    ) -> None:
        config = self.load_graph_config()
        client = self._client_for_config(config)
        client.send_mail(
            to_email=to_email,
            subject=subject,
            body_text=str(text_body or "").strip(),
            body_html=str(html_body or "").strip(),
            attachments=list(attachments or []),
        )

    @staticmethod
    def plain_text_to_html(value: str) -> str:
        normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return "<p></p>"
        paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", normalized) if chunk.strip()]
        html_parts: list[str] = []
        for paragraph in paragraphs:
            escaped = html.escape(paragraph).replace("\n", "<br>")
            html_parts.append(f"<p>{escaped}</p>")
        return "\n".join(html_parts)

    def _client_for_config(self, config: GraphMailConfig) -> GraphMailClient:
        key = (config.tenant_id, config.client_id, config.mailbox_user, str(config.cache_path))
        if self._client is None or self._client_key != key:
            self._client = GraphMailClient(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                mailbox_user=config.mailbox_user or None,
                cache_path=config.cache_path,
            )
            self._client_key = key
        return self._client

    def _secret_or_env(self, key: str, default: str = "") -> str:
        value = ""
        if self._secrets is not None:
            value = str(self._secrets.get_secret(key) or "").strip()
        if value:
            return value
        return str(os.getenv(key) or default).strip()
