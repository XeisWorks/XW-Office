"""Server-side, app-only Microsoft Graph access for private product assets."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

import msal
import requests


class OneDriveConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OneDriveItem:
    drive_id: str
    item_id: str
    name: str
    etag: str
    size: int
    parent_id: str = ""
    is_folder: bool = False


class OneDriveAssetClient:
    """Uses client credentials; never exposes Graph tokens to browser clients."""

    def __init__(self, *, tenant_id: str, client_id: str, client_secret: str, root_item_id: str = "") -> None:
        self.tenant_id, self.client_id, self.client_secret = tenant_id.strip(), client_id.strip(), client_secret.strip()
        self.root_item_id = root_item_id.strip()
        if not all((self.tenant_id, self.client_id, self.client_secret, self.root_item_id)):
            raise OneDriveConfigurationError("OneDrive server access is not configured")
        if "\\" in self.root_item_id or ":" not in self.root_item_id:
            raise OneDriveConfigurationError("XW_ONEDRIVE_ROOT must be drive_id:item_id")
        self.root_drive_id, self.root_item_id = self.root_item_id.split(":", 1)
        if not self.root_drive_id or not self.root_item_id:
            raise OneDriveConfigurationError("XW_ONEDRIVE_ROOT must be drive_id:item_id")
        self._app = msal.ConfidentialClientApplication(self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant_id}", client_credential=self.client_secret)

    @classmethod
    def from_environment(cls) -> "OneDriveAssetClient":
        return cls(tenant_id=os.getenv("MS_GRAPH_TENANT_ID", ""), client_id=os.getenv("MS_GRAPH_CLIENT_ID", ""), client_secret=os.getenv("MS_GRAPH_CLIENT_SECRET", ""), root_item_id=os.getenv("XW_ONEDRIVE_ROOT", ""))

    def _headers(self) -> dict[str, str]:
        result = self._app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        token = str(result.get("access_token") or "")
        if not token:
            raise OneDriveConfigurationError("Microsoft Graph token acquisition failed")
        return {"Authorization": f"Bearer {token}"}

    def get_item(self, drive_id: str, item_id: str) -> OneDriveItem:
        response = requests.get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}", headers=self._headers(), timeout=30)
        response.raise_for_status()
        return self._item_from_payload(drive_id, response.json())

    @staticmethod
    def _item_from_payload(drive_id: str, payload: dict[str, object]) -> OneDriveItem:
        parent = payload.get("parentReference")
        parent_id = str(parent.get("id") or "") if isinstance(parent, dict) else ""
        return OneDriveItem(
            drive_id=drive_id,
            item_id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            etag=str(payload.get("eTag") or ""),
            size=int(payload.get("size") or 0),
            parent_id=parent_id,
            is_folder=isinstance(payload.get("folder"), dict),
        )

    def get_root(self) -> OneDriveItem:
        return self.get_item(self.root_drive_id, self.root_item_id)

    def resolve_relative_folder(self, relative_path: str) -> OneDriveItem:
        """Resolve a human-maintained path below the approved root to one stable ID.

        Paths are a deployment convenience only: all later reads still use the
        opaque item ID and are checked against the configured root.  This keeps
        Windows sync paths out of server configuration while allowing a folder
        selected in OneDrive to be named naturally.
        """
        parts = [part.strip() for part in relative_path.replace("\\", "/").split("/")]
        if not parts or any(not part or part in {".", ".."} for part in parts):
            raise OneDriveConfigurationError("OneDrive relative folder path is invalid")
        encoded_path = "/".join(quote(part, safe="") for part in parts)
        response = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{self.root_drive_id}/items/{self.root_item_id}:/{encoded_path}",
            headers=self._headers(),
            params={"$select": "id,name,eTag,size,folder,parentReference"},
            timeout=30,
        )
        response.raise_for_status()
        item = self._item_from_payload(self.root_drive_id, response.json())
        if not item.item_id or not item.is_folder:
            raise OneDriveConfigurationError("Configured OneDrive path is not a folder")
        self.assert_within_root(item.drive_id, item.item_id)
        return item

    def list_children(self, item_id: str | None = None, *, limit: int = 100) -> list[OneDriveItem]:
        """List immediate children of the configured root only."""
        parent_id = item_id or self.root_item_id
        self.assert_within_root(self.root_drive_id, parent_id)
        response = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{self.root_drive_id}/items/{parent_id}/children",
            headers=self._headers(),
            params={"$select": "id,name,eTag,size,folder,parentReference", "$top": min(max(limit, 1), 100)},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        values = payload.get("value", [])
        if not isinstance(values, list):
            raise OneDriveConfigurationError("Microsoft Graph returned an invalid child listing")
        return [self._item_from_payload(self.root_drive_id, value) for value in values if isinstance(value, dict)]

    def assert_within_root(self, drive_id: str, item_id: str) -> None:
        """Reject IDs outside the configured subtree before reading their content."""
        if drive_id != self.root_drive_id:
            raise ValueError("The selected item is outside the configured OneDrive drive")
        current_id = item_id
        # Graph item IDs are opaque. Following parent IDs avoids fragile path/name
        # matching and also catches a file moved outside the approved root.
        for _ in range(100):
            if current_id == self.root_item_id:
                return
            current = self.get_item(drive_id, current_id)
            if not current.parent_id:
                break
            current_id = current.parent_id
        raise ValueError("The selected item is outside the configured OneDrive root")

    def download(self, drive_id: str, item_id: str) -> bytes:
        response = requests.get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content", headers=self._headers(), timeout=60)
        response.raise_for_status()
        return response.content
