"""Wix Data (CMS collections) REST client.

Lets XW-Studio read and write Wix CMS collections (e.g. MH-Tracks, MH-Editions)
directly with the API key, without depending on a Wix-site-admin browser session.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from xw_office.services.filename_generator.models import FilenameGeneratorError

if TYPE_CHECKING:
    from xw_office.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_API_BASE = "https://www.wixapis.com/wix-data/v2"
_TIMEOUT = 20.0
_QUERY_PAGE_LIMIT = 1000


class WixDataClient:
    """Read/write access to Wix CMS collections via the Wix Data REST API."""

    def __init__(
        self,
        secret_service: SecretService,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._secrets = secret_service
        self._transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key() and self._site_id())

    def _api_key(self) -> str:
        # Mirrors WixMediaUploadService: a narrower media/CMS key may be set only
        # via environment variable, separate from the general integration key.
        data_key = os.getenv("WIX_API_KEY_DATA", "").strip()
        return data_key or str(self._secrets.get_secret("WIX_API_KEY") or "").strip()

    def _site_id(self) -> str:
        return str(self._secrets.get_secret("WIX_SITE_ID") or "").strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key(),
            "wix-site-id": self._site_id(),
            "Content-Type": "application/json",
        }

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise FilenameGeneratorError(
                "Wix ist nicht konfiguriert. Bitte WIX_API_KEY und WIX_SITE_ID in den Einstellungen prüfen."
            )

    def query_all_items(
        self,
        collection_id: str,
        *,
        limit: int = _QUERY_PAGE_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return every item of a collection in one page.

        Raises if the collection holds at least `limit` items, matching the
        safety limit used by the previous Wix-side importer.
        """
        self._require_configured()
        with httpx.Client(
            base_url=_API_BASE, headers=self._headers(), timeout=_TIMEOUT, transport=self._transport
        ) as client:
            response = client.post(
                "/items/query",
                json={
                    "dataCollectionId": collection_id,
                    "query": {"paging": {"limit": limit}},
                },
            )
            payload = self._response_json(response, f'Collection "{collection_id}" lesen')
        raw_items = payload.get("dataItems")
        items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
        paging = payload.get("pagingMetadata") if isinstance(payload.get("pagingMetadata"), dict) else {}
        count = int(paging.get("count") or len(items))
        if count >= limit:
            raise FilenameGeneratorError(
                f'Die Importgrenze von {limit} Datensätzen für "{collection_id}" wurde erreicht. '
                "Der Import wurde sicherheitshalber abgebrochen."
            )
        return [self._flatten_item(item) for item in items]

    def insert_item(self, collection_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        with httpx.Client(
            base_url=_API_BASE, headers=self._headers(), timeout=_TIMEOUT, transport=self._transport
        ) as client:
            response = client.post(
                "/items",
                json={"dataCollectionId": collection_id, "dataItem": {"data": data}},
            )
            payload = self._response_json(response, f'Datensatz in "{collection_id}" anlegen')
        item = payload.get("dataItem")
        return self._flatten_item(item if isinstance(item, dict) else {})

    def update_item(self, collection_id: str, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        iid = str(item_id or "").strip()
        if not iid:
            raise FilenameGeneratorError("Die Datensatz-ID fehlt für das Update.")
        with httpx.Client(
            base_url=_API_BASE, headers=self._headers(), timeout=_TIMEOUT, transport=self._transport
        ) as client:
            response = client.put(
                f"/items/{iid}",
                json={"dataCollectionId": collection_id, "dataItem": {"id": iid, "data": data}},
            )
            payload = self._response_json(response, f'Datensatz in "{collection_id}" aktualisieren')
        item = payload.get("dataItem")
        return self._flatten_item(item if isinstance(item, dict) else {})

    @staticmethod
    def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
        """Merge Wix Data's ``{id, data: {...}}`` envelope into one flat dict with ``_id``."""
        raw_data = item.get("data")
        flat: dict[str, Any] = dict(raw_data) if isinstance(raw_data, dict) else {}
        item_id = str(item.get("id") or flat.get("_id") or "").strip()
        if item_id:
            flat["_id"] = item_id
        return flat

    @staticmethod
    def _response_json(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = ""
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    message = str(error_payload.get("message") or "").strip()
            except (ValueError, AttributeError):
                pass
            detail = f": {message}" if message else f" (HTTP {response.status_code})"
            raise FilenameGeneratorError(operation + detail) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise FilenameGeneratorError(f"{operation}: Wix lieferte keine JSON-Antwort.") from exc
        if not isinstance(payload, dict):
            raise FilenameGeneratorError(f"{operation}: Unerwartete Wix-Antwort.")
        return payload
