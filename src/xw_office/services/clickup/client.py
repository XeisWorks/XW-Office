"""ClickUp API v2 client — creates tasks via personal API token."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from xw_office.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.clickup.com/api/v2"
_TIMEOUT = 15.0


class ClickUpTask(BaseModel):
    """Minimal task representation returned by the API."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    url: str = ""
    status: str = ""


class ClickUpClient:
    """Create and query ClickUp tasks.

    Credentials are read from :class:`SecretService` (key: CLICKUP_API_TOKEN).
    ``list_id`` can be supplied per call or set as a default at construction.
    """

    def __init__(
        self,
        secret_service: SecretService,
        *,
        default_list_id: str = "",
    ) -> None:
        self._secret_service = secret_service
        self._default_list_id = default_list_id

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def has_credentials(self) -> bool:
        """Return True when CLICKUP_API_TOKEN is set."""
        token = self._token()
        return bool(token)

    def create_task(
        self,
        title: str,
        *,
        description: str = "",
        list_id: str = "",
        priority: int | None = None,
        tags: list[str] | None = None,
    ) -> ClickUpTask:
        """Create a new task.

        Parameters
        ----------
        title:
            Task name (required).
        description:
            Optional plain-text description.
        list_id:
            ClickUp list ID.  Falls back to ``default_list_id`` if omitted.
        priority:
            1 = urgent, 2 = high, 3 = normal, 4 = low.
        tags:
            Optional list of tag names.

        Raises
        ------
        ValueError
            When no API token or no list ID is available.
        httpx.HTTPStatusError
            On API errors (4xx / 5xx).
        """
        token = self._token()
        if not token:
            raise ValueError("CLICKUP_API_TOKEN ist nicht konfiguriert.")
        lid = list_id or self._default_list_id
        if not lid:
            raise ValueError("Keine ClickUp-Listen-ID angegeben (list_id).")

        payload: dict[str, Any] = {"name": title}
        if description:
            payload["description"] = description
        if priority is not None:
            payload["priority"] = priority
        if tags:
            payload["tags"] = tags

        url = f"{_BASE_URL}/list/{lid}/task"
        headers = {"Authorization": token, "Content-Type": "application/json"}
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        task = ClickUpTask(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or title),
            url=str(data.get("url") or ""),
            status=str((data.get("status") or {}).get("status") or ""),
        )
        logger.info("ClickUp task created: %s (%s)", task.name, task.id)
        return task

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _token(self) -> str:
        try:
            return self._secret_service.get_secret("CLICKUP_API_TOKEN") or ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("ClickUpClient: token fetch failed: %s", exc)
            return ""
