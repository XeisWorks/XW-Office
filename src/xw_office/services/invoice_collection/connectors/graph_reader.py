"""Read-only Microsoft Graph mail attachment reader with injected token provider."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from xw_office.services.invoice_collection.auth.graph import GraphTokenProvider
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)


class GraphMailAttachmentReader:
    """Fetch message metadata and actual attachment bytes, never message links."""

    def __init__(
        self,
        *,
        mailbox: str,
        token_provider: GraphTokenProvider,
        client: httpx.Client | None = None,
        base_url: str = "https://graph.microsoft.com/v1.0",
        max_attachment_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        if not mailbox.strip():
            raise ValueError("mailbox is required")
        self.mailbox = mailbox.strip()
        self.token_provider = token_provider
        self.client = client or httpx.Client(timeout=httpx.Timeout(30.0))
        self.base_url = base_url.rstrip("/")
        self.max_attachment_bytes = max_attachment_bytes

    def list_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        url: str | None = (
            f"{self.base_url}/users/{quote(self.mailbox, safe='@.')}/messages"
            "?$select=id,receivedDateTime,sender&$expand=attachments"
            "($select=id,name,contentType,size,isInline)&$top=100"
        )
        while url:
            payload = self._request("GET", url).json()
            for raw in payload.get("value") or []:
                if not isinstance(raw, dict):
                    continue
                sender = ((raw.get("sender") or {}).get("emailAddress") or {})
                attachments = []
                for attachment in raw.get("attachments") or []:
                    if not isinstance(attachment, dict) or attachment.get("isInline"):
                        continue
                    attachments.append(
                        {
                            "id": attachment.get("id"),
                            "name": attachment.get("name"),
                            "content_type": attachment.get("contentType"),
                            "size": attachment.get("size"),
                        }
                    )
                messages.append(
                    {
                        "id": raw.get("id"),
                        "received_at": raw.get("receivedDateTime"),
                        "sender_domain": _sender_domain(sender.get("address")),
                        "attachments": attachments,
                    }
                )
            next_link = payload.get("@odata.nextLink")
            url = str(next_link) if next_link else None
        return messages

    def download_attachment(self, message_id: str, attachment_id: str, destination: Path) -> None:
        url = (
            f"{self.base_url}/users/{quote(self.mailbox, safe='@.')}/messages/"
            f"{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}"
        )
        response = self._request("GET", url)
        payload: bytes
        if response.headers.get("content-type", "").casefold().startswith("application/json"):
            content = response.json().get("contentBytes")
            if not content:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.INVALID_DOCUMENT, "Graph-Anhang enthält keine Bytes"
                )
            payload = base64.b64decode(content)
        else:
            payload = response.content
        if not payload or len(payload) > self.max_attachment_bytes:
            raise InvoiceCollectionError(
                InvoiceErrorCode.INVALID_DOCUMENT, "Graph-Anhang hat eine ungültige Größe"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, url: str) -> httpx.Response:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "graph.microsoft.com":
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED, "Graph-URL ist nicht erlaubt"
            )
        token = self.token_provider.get_access_token()
        response = self.client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if response.status_code in {401, 403}:
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED, "Microsoft-Graph-Zugriff wurde abgelehnt"
            )
        if response.status_code == 429:
            raise InvoiceCollectionError(
                InvoiceErrorCode.RATE_LIMITED, "Microsoft Graph hat den Abruf begrenzt"
            )
        if response.status_code >= 500:
            raise InvoiceCollectionError(
                InvoiceErrorCode.TRANSIENT_NETWORK,
                "Microsoft Graph ist vorübergehend nicht erreichbar",
            )
        response.raise_for_status()
        return response


def _sender_domain(address: Any) -> str:
    text = str(address or "").strip().casefold()
    return text.rsplit("@", 1)[-1] if "@" in text else ""
