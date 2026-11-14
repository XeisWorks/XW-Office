"""Read-only Microsoft Graph mail attachment reader with injected token provider."""
from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterator
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

    def list_messages(self) -> Iterator[dict[str, Any]]:
        url: str | None = (
            f"{self.base_url}/users/{quote(self.mailbox, safe='@.')}/messages"
            "?$filter=hasAttachments%20eq%20true&$select=id,receivedDateTime,sender&$expand=attachments"
            "($select=id,name,contentType,size,isInline)&$top=100"
        )
        seen_page_links: set[str] = set()
        while url:
            if url in seen_page_links:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.TRANSIENT_NETWORK,
                    "Microsoft Graph hat einen wiederholten Seitenlink geliefert",
                )
            seen_page_links.add(url)
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
                yield {
                    "id": raw.get("id"),
                    "received_at": raw.get("receivedDateTime"),
                    "sender_domain": _sender_domain(sender.get("address")),
                    "attachments": attachments,
                }
            next_link = payload.get("@odata.nextLink")
            url = str(next_link) if next_link else None

    def probe_mailbox(self) -> None:
        """Verify delegated mailbox access without reading message content or attachments."""
        url = (
            f"{self.base_url}/users/{quote(self.mailbox, safe='@.')}/messages"
            "?$select=id&$top=1"
        )
        self._request("GET", url)

    def download_attachment(self, message_id: str, attachment_id: str, destination: Path) -> None:
        url = (
            f"{self.base_url}/users/{quote(self.mailbox, safe='@.')}/messages/"
            f"{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}"
        )
        self._validate_graph_url(url)
        headers = {
            "Authorization": f"Bearer {self.token_provider.get_access_token()}",
            "Accept": "application/json",
        }
        with self.client.stream("GET", url, headers=headers) as response:
            self._check_response(response)
            is_json = response.headers.get("content-type", "").casefold().startswith(
                "application/json"
            )
            response_limit = (
                _max_base64_length(self.max_attachment_bytes) + _JSON_ATTACHMENT_OVERHEAD
                if is_json
                else self.max_attachment_bytes
            )
            _reject_declared_oversize(response, response_limit)
            body = _read_limited(response, response_limit)
        payload = (
            _decode_graph_attachment(body, self.max_attachment_bytes)
            if is_json
            else body
        )
        if not payload or len(payload) > self.max_attachment_bytes:
            raise _invalid_attachment_size()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, url: str) -> httpx.Response:
        self._validate_graph_url(url)
        token = self.token_provider.get_access_token()
        response = self.client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        self._check_response(response)
        return response

    @staticmethod
    def _validate_graph_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "graph.microsoft.com":
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED, "Graph-URL ist nicht erlaubt"
            )

    @staticmethod
    def _check_response(response: httpx.Response) -> None:
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


_STREAM_CHUNK_BYTES = 64 * 1024
_JSON_ATTACHMENT_OVERHEAD = 64 * 1024


def _max_base64_length(max_decoded_bytes: int) -> int:
    return ((max_decoded_bytes + 2) // 3) * 4


def _reject_declared_oversize(response: httpx.Response, limit: int) -> None:
    """Use Content-Length as an early rejection hint; streaming remains authoritative."""
    try:
        declared_length = int(response.headers.get("content-length", ""))
    except ValueError:
        return
    if declared_length > limit:
        raise _invalid_attachment_size()


def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=_STREAM_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise _invalid_attachment_size()
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_graph_attachment(body: bytes, max_attachment_bytes: int) -> bytes:
    try:
        payload_json = json.loads(body)
        content = payload_json.get("contentBytes") if isinstance(payload_json, dict) else None
        if not isinstance(content, str) or not content:
            raise ValueError("contentBytes missing")
        if len(content) > _max_base64_length(max_attachment_bytes):
            raise _invalid_attachment_size()
        payload = base64.b64decode(content, validate=True)
    except InvoiceCollectionError:
        raise
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError):
        raise InvoiceCollectionError(
            InvoiceErrorCode.INVALID_DOCUMENT,
            "Graph-Anhang enthält ungültige JSON-/Base64-Daten",
        ) from None
    if not payload or len(payload) > max_attachment_bytes:
        raise _invalid_attachment_size()
    return payload


def _invalid_attachment_size() -> InvoiceCollectionError:
    return InvoiceCollectionError(
        InvoiceErrorCode.INVALID_DOCUMENT, "Graph-Anhang hat eine ungültige Größe"
    )


def _sender_domain(address: Any) -> str:
    text = str(address or "").strip().casefold()
    return text.rsplit("@", 1)[-1] if "@" in text else ""
